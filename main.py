import os
import click
import pandas as pd
import re
import numpy as np
from flask import Flask, render_template
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_migrate import Migrate
from urllib.parse import urlencode, parse_qs

db = SQLAlchemy()
cache = Cache()
migrate = Migrate()

def clean_col_name(col_name):
    s = re.sub(r'[^a-zA-Z0-9_]', ' ', str(col_name))
    s = re.sub(r'\s+', '_', s).strip().lower()
    if s and s[0].isdigit():
        s = '_' + s
    return s

def remove_filter(query_bytes, filter_key, value_to_remove):
    """
    Removes a specific value from a filter in the query string.
    """
    params = parse_qs(query_bytes.decode('utf-8'))
    if filter_key in params:
        params[filter_key] = [v for v in params[filter_key] if v != value_to_remove]
        if not params[filter_key]:
            del params[filter_key]
    return urlencode(params, doseq=True)

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(app.instance_path, 'app.db')}",
        CACHE_TYPE='SimpleCache',
        CACHE_DEFAULT_TIMEOUT=300
    )

    app.jinja_env.add_extension('jinja2.ext.do')

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)
    cache.init_app(app)
    migrate.init_app(app, db)

    app.jinja_env.filters['remove_filter'] = remove_filter

    app.cli.add_command(init_db_command)
    app.cli.add_command(load_data_command)
    app.cli.add_command(migrate_data_command)
    app.cli.add_command(populate_restored_columns_command)
    app.cli.add_command(normalize_components_command)

    @app.route("/")
    def index():
        return render_template('index.html')

    from mpr import mpr_bp
    app.register_blueprint(mpr_bp, url_prefix='/mpr')

    from mpr import models

    return app

@click.command('init-db')
@with_appcontext
def init_db_command():
    db.create_all()
    click.echo('Initialized the database.')

@click.command('load-data')
@with_appcontext
def load_data_command():
    from mpr.models import MprReport
    file_path = 'ALL_2025_October.xlsx'
    sheet_name = 'data'
    try:
        num_deleted = db.session.query(MprReport).delete()
        click.echo(f'Clearing {num_deleted} existing records from the mpr_report table.')
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df.columns = [clean_col_name(col) for col in df.columns]
        date_columns = ['pab_date', 'tentative_date_of_completion']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        if 's_no' in df.columns:
            df = df.drop(columns=['s_no'])
        click.echo(f'Loading {len(df.index)} records from {file_path}...')
        for _, row in df.iterrows():
            record_data = {}
            for key, value in row.to_dict().items():
                if pd.isna(value):
                    record_data[key] = None
                elif isinstance(value, pd.Timestamp):
                    record_data[key] = value.to_pydatetime()
                else:
                    record_data[key] = value
            valid_keys = [c.name for c in MprReport.__table__.columns]
            filtered_data = {k: v for k, v in record_data.items() if k in valid_keys}
            record = MprReport(**filtered_data)
            db.session.add(record)
        db.session.commit()
        click.echo(f'Database seeded successfully. Loaded {len(df.index)} new records.')
    except FileNotFoundError:
        click.echo(f"Error: The file '{file_path}' was not found.")
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        click.echo(f"An error occurred, transaction rolled back: {e}")

@click.command('migrate-data')
@with_appcontext
def migrate_data_command():
    from mpr.models import State, RusaPhase, MprReport
    click.echo('Starting data migration...')

    def normalize_name(name):
        if not isinstance(name, str):
            return None
        return name.lower().strip().replace('&', 'and')

    try:
        # Seed states if they don't exist
        STATES = [
            'Andaman & Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam',
            'Bihar', 'Chandigarh', 'Chhattisgarh', 'Dadra and Nagar Haveli and Daman and Diu',
            'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu & Kashmir',
            'Jharkhand', 'Karnataka', 'Kerala', 'Ladakh', 'Lakshdweep', 'Madhya Pradesh',
            'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab',
            'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh',
            'Uttarakhand', 'West Bengal'
        ]
        for state_name in STATES:
            if not db.session.query(State).filter_by(name=state_name).first():
                db.session.add(State(name=state_name))
        db.session.commit()
        click.echo('Seeded states table.')

        # Seed RUSA phases if they don't exist
        RUSA_PHASES = ['RUSA 1', 'RUSA 2', 'PM-UShA']
        for phase_name in RUSA_PHASES:
            if not db.session.query(RusaPhase).filter_by(name=phase_name).first():
                db.session.add(RusaPhase(name=phase_name))
        db.session.commit()
        click.echo('Seeded RUSA phases table.')

        # Create normalized maps for robust matching
        states_map = {normalize_name(s.name): s.id for s in db.session.query(State).all()}
        phases_map = {normalize_name(p.name): p.id for p in db.session.query(RusaPhase).all()}

        # Add manual mappings for known inconsistencies
        states_map['dadra and nagar haveli'] = states_map.get(normalize_name('Dadra and Nagar Haveli and Daman and Diu'))
        states_map['the dadra and nagar haveli and daman and diu'] = states_map.get(normalize_name('Dadra and Nagar Haveli and Daman and Diu'))

        unmatched_states = set()
        unmatched_phases = set()

        reports = db.session.query(MprReport).all()
        total_reports = len(reports)
        click.echo(f'Found {total_reports} reports to migrate.')
        
        for i, report in enumerate(reports, 1):
            # Match state
            normalized_report_state = normalize_name(report.state)
            if normalized_report_state and normalized_report_state in states_map:
                report.state_id = states_map[normalized_report_state]
            elif report.state:
                unmatched_states.add(report.state)

            # Match RUSA phase
            normalized_report_phase = normalize_name(report.rusa_phase)
            if normalized_report_phase and normalized_report_phase in phases_map:
                report.rusa_phase_id = phases_map[normalized_report_phase]
            elif report.rusa_phase:
                unmatched_phases.add(report.rusa_phase)

            if i % 100 == 0 or i == total_reports:
                 click.echo(f'  Processed {i}/{total_reports} reports...')
        
        db.session.commit()

        # Report any unmatched values
        if unmatched_states:
            click.echo(f"Warning: Could not match the following states: {sorted(list(unmatched_states))}")
        if unmatched_phases:
            click.echo(f"Warning: Could not match the following RUSA phases: {sorted(list(unmatched_phases))}")

        click.echo('Data migration successful!')

    except Exception as e:
        db.session.rollback()
        click.echo(f"An error occurred during migration, transaction rolled back: {e}")

@click.command('populate-restored-columns')
@with_appcontext
def populate_restored_columns_command():
    """Populates the restored columns from the Excel file."""
    from mpr.models import MprReport
    file_path = 'ALL_2025_October.xlsx'
    sheet_name = 'data'
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df.columns = [clean_col_name(col) for col in df.columns]
        df['year'] = pd.to_numeric(df['year'], errors='coerce').astype('Int64')
        df = df.replace({np.nan: None})
        click.echo(f'Processing {len(df.index)} records from {file_path}...')
        update_count = 0
        not_found_count = 0
        for _, row in df.iterrows():
            filter_criteria = {
                'state': row['state'],
                'rusa_phase': row['rusa_phase'],
                'component_name': row['component_name'],
                'institution_name': row['institution_name'],
                'district': row['district'],
                'months': row['months'],
                'year': None if pd.isna(row['year']) else row['year']
            }
            record = MprReport.query.filter_by(**filter_criteria).first()
            if record:
                def get_value(row_data, key):
                    val = row_data.get(key)
                    if pd.isna(val):
                        return None
                    return val
                record.benfits_from_the_projects_please_provide_details_ = get_value(row, 'benfits_from_the_projects_please_provide_details_')
                record.number_of_students_benefitted = get_value(row, 'number_of_students_benefitted')
                record.number_of_faculties_benefitted = get_value(row, 'number_of_faculties_benefitted')
                record.number_of_research_works_being_undertaken = get_value(row, 'number_of_research_works_being_undertaken')
                record.physical_inspection_reports_pir_ = get_value(row, 'physical_inspection_reports_pir_')
                record.pir_uploaded_yes_no_not_selected_ = get_value(row, 'pir_uploaded_yes_no_not_selected_')
                update_count += 1
            else:
                not_found_count += 1
        db.session.commit()
        click.echo(f'Successfully processed records. Updated: {update_count}, Not Found: {not_found_count}.')
    except FileNotFoundError:
        click.echo(f"Error: The file '{file_path}' was not found.")
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        click.echo(f"An error occurred, transaction rolled back: {e}")

@click.command('normalize-components')
@with_appcontext
def normalize_components_command():
    """Seeds the components and associates them with RUSA phases."""
    from mpr.models import RusaPhase, Component, MprReport

    COMPONENTS_DATA = {
        'RUSA 1': [
            'Vocationalisation of Higher Education',
            'Upgradation of Existing Degree College to Model Degree College',
            'Research Innovation & Quality Improvement',
            'Preparatory Grants',
            'New Model Degree Colleges',
            'New Colleges (Professional & Technical)',
            'Infrastructure Grants to Universities',
            'Infrastructure Grants to Colleges',
            'Faculty Recruitment Support',
            'Faculty Improvement',
            'Estwhile MDC',
            'Creation of Universities by way of Upgradation of Existing Autonomous Colleges',
            'Creation of Universities by Conversion of Colleges in a Cluster'
        ],
        'RUSA 2': [
            'Upgradation of Existing Degree College to Model Degree College',
            'Research Innovation & Quality Improvement',
            'Preparatory Grants',
            'New Model Degree Colleges',
            'New Colleges (Professional & Technical)',
            'Infrastructure Grants to Colleges',
            'Faculty Recruitment Support',
            'Faculty Improvement',
            'Estwhile MDC',
            'Equity Initiative',
            'Enhancing Quality and Excellence in select State Universities',
            'Enhancing Quality and Excellence in Select Autonomous Colleges',
            'Creation of Universities by way of Upgradation of Existing Autonomous Colleges',
            'Creation of Universities by Conversion of Colleges in a Cluster',
            'Infrastructure Grants to Universities',
            'Vocationalisation of Higher Education'
        ],
        'PM-UShA': [
            'Multi-Disciplinary Education and Research Universities (MERU)',
            'Grants to Strengthen Universities (Accredited & Unaccredited Universities)',
            'Grants to Strengthen Colleges (Accredited & Unaccredited Colleges)',
            'Gender Inclusion and Equity Initiatives'
        ]
    }

    try:
        # Seed Components
        all_components = set()
        for components in COMPONENTS_DATA.values():
            for component_name in components:
                all_components.add(component_name)

        for component_name in all_components:
            if not db.session.query(Component).filter_by(name=component_name).first():
                db.session.add(Component(name=component_name))
        db.session.commit()
        click.echo('Seeded components table.')

        # Associate Components with RUSA Phases
        phases_map = {p.name: p for p in db.session.query(RusaPhase).all()}
        components_map = {c.name: c for c in db.session.query(Component).all()}

        for phase_name, component_names in COMPONENTS_DATA.items():
            if phase_name in phases_map:
                phase = phases_map[phase_name]
                for component_name in component_names:
                    if component_name in components_map:
                        component = components_map[component_name]
                        if component not in phase.components:
                            phase.components.append(component)
        db.session.commit()
        click.echo('Associated components with RUSA phases.')

        # Update MprReport table
        reports = db.session.query(MprReport).all()
        total_reports = len(reports)
        click.echo(f'Found {total_reports} reports to update.')
        for i, report in enumerate(reports, 1):
            if report.component_name and report.component_name in components_map:
                report.component_id = components_map[report.component_name].id
            if i % 100 == 0 or i == total_reports:
                 click.echo(f'  Processed {i}/{total_reports} reports...')
        db.session.commit()
        click.echo('Updated component_id in mpr_report table.')

        click.echo('Component normalization successful!')

    except Exception as e:
        db.session.rollback()
        click.echo(f"An error occurred during component normalization, transaction rolled back: {e}")

app = create_app()

if __name__ == '__main__':
    app.run(port=int(os.environ.get('PORT', 80)))