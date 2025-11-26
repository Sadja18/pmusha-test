
import os
import click
import pandas as pd
import re
from flask import Flask, render_template
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache

# Initialize extensions but don't bind to an app yet
db = SQLAlchemy()
cache = Cache()

# --- Utility Functions for Data Loading ---
def clean_col_name(col_name):
    """Cleans a string to make it a valid Python identifier."""
    s = re.sub(r'[^a-zA-Z0-9_]', ' ', str(col_name))
    s = re.sub(r'\s+', '_', s).strip().lower()
    if s and s[0].isdigit():
        s = '_' + s
    return s

# --- Application Factory ---
def create_app():
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev', # Should be overridden in production
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(app.instance_path, 'app.db')}",
        CACHE_TYPE='SimpleCache', # In-memory cache
        CACHE_DEFAULT_TIMEOUT=300 # 5 minutes
    )

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize Flask extensions
    db.init_app(app)
    cache.init_app(app)

    # Register CLI commands
    app.cli.add_command(init_db_command)
    app.cli.add_command(load_data_command)

    # --- Blueprints and Routes ---
    @app.route("/")
    def index():
        return render_template('index.html')

    from mpr import mpr_bp
    app.register_blueprint(mpr_bp, url_prefix='/mpr')

    # Import models so they are registered for discovery
    from mpr import models

    return app

# --- CLI Commands ---
@click.command('init-db')
@with_appcontext
def init_db_command():
    """Create new tables in the database."""
    db.create_all()
    click.echo('Initialized the database.')

@click.command('load-data')
@with_appcontext
def load_data_command():
    """Clears and seeds data from Excel into the database."""
    from mpr.models import MprReport

    file_path = 'ALL_2025_October.xlsx'
    sheet_name = 'data'
    try:
        # Clear existing data from the MprReport table
        num_deleted = db.session.query(MprReport).delete()
        click.echo(f'Clearing {num_deleted} existing records from the mpr_report table.')

        df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        df.columns = [clean_col_name(col) for col in df.columns]

        # Explicitly convert date columns, coercing errors to NaT (Not a Time)
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
                # Convert pandas Timestamps to Python datetimes for SQLite
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

# Create the app instance for the Flask CLI
app = create_app()

if __name__ == '__main__':
    app.run(port=int(os.environ.get('PORT', 80)))
