
from flask import render_template, request
from sqlalchemy import desc, case, func, and_
from sqlalchemy.orm import contains_eager
from . import mpr_bp
from main import cache
from .models import MprReport, Component, RusaPhase, State
from collections import defaultdict

def get_distinct_values(model, column):
    """Helper function to get distinct, non-empty values for a column from a specific model."""
    return [r[0] for r in model.query.with_entities(column).distinct().filter(column.isnot(None), column != '').order_by(column).all()]

@mpr_bp.route('/records')
@cache.cached(timeout=300, query_string=True)
def records():
    """Displays a paginated and filterable list of all MPR records with an analytical summary."""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    filters = {
        'state': request.args.getlist('state'),
        'rusa_phase': request.args.getlist('rusa_phase'),
        'component_name': request.args.getlist('component_name'),
        'institution_name': request.args.getlist('institution_name'),
        'district': request.args.getlist('district'),
        'project_status': request.args.getlist('project_status'),
        'year': request.args.getlist('year'),
        'months': request.args.getlist('months'),
    }

    # Base query with outer joins to ensure all records are included and relationships can be eagerly loaded.
    query = MprReport.query.outerjoin(MprReport.state_rel).outerjoin(MprReport.rusa_phase_rel).outerjoin(MprReport.component_rel)

    # Apply filters to the query
    if filters['state']:
        query = query.filter(State.name.in_(filters['state']))
    if filters['rusa_phase']:
        query = query.filter(RusaPhase.name.in_(filters['rusa_phase']))
    if filters['component_name']:
        query = query.filter(Component.name.in_(filters['component_name']))
    if filters['institution_name']:
        query = query.filter(MprReport.institution_name.in_(filters['institution_name']))
    if filters['district']:
        query = query.filter(MprReport.district.in_(filters['district']))
    if filters['project_status']:
        query = query.filter(MprReport.project_status.in_(filters['project_status']))
    if filters['year']:
        query = query.filter(MprReport.year.in_([int(y) for y in filters['year']]))
    if filters['months']:
        query = query.filter(MprReport.months.in_(filters['months']))

    month_order = case(
        {'December': 12, 'November': 11, 'October': 10, 'September': 9, 'August': 8, 'July': 7, 'June': 6, 'May': 5, 'April': 4, 'March': 3, 'February': 2, 'January': 1},
        value=MprReport.months, else_=0
    )

    # For the main table, explicitly load the relationships to ensure data is available in the template.
    paginated_query = query.options(
        contains_eager(MprReport.state_rel),
        contains_eager(MprReport.rusa_phase_rel),
        contains_eager(MprReport.component_rel)
    )
    
    sorted_query = paginated_query.order_by(
        desc(MprReport.year), desc(month_order), State.name, RusaPhase.name
    )

    pagination = sorted_query.paginate(page=page, per_page=per_page, error_out=False)

    summary_data = {}
    # Use the filtered query to check for existence efficiently.
    filtered_records_exist = query.session.query(query.exists()).scalar()

    if filtered_records_exist:
        # Analytics queries should only consider records with valid, non-null grouping keys.
        analytics_query = query.filter(State.name.isnot(None), RusaPhase.name.isnot(None), Component.name.isnot(None))

        interactive_summary_query = analytics_query.with_entities(
            State.name.label('state'),
            RusaPhase.name.label('rusa_phase'),
            func.count(MprReport.id).label('total'),
            func.sum(case((MprReport.project_status == 'Ongoing', 1), else_=0)).label('ongoing'),
            func.sum(case((MprReport.project_status == 'Completed', 1), else_=0)).label('completed'),
            func.sum(case((MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', 1), else_=0)).label('pm_launched'),
            func.sum(case((and_(MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', MprReport.project_status == 'Ongoing'), 1), else_=0)).label('pm_ongoing'),
            func.sum(case((and_(MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', MprReport.project_status == 'Completed'), 1), else_=0)).label('pm_completed')
        ).group_by(State.name, RusaPhase.name).order_by(State.name, RusaPhase.name).all()

        state_summary_interactive = defaultdict(lambda: { 
            cat: {'count': 0, 'phases': defaultdict(int)} for cat in ['total', 'ongoing', 'completed', 'pm_launched', 'pm_ongoing', 'pm_completed']
        })

        for row in interactive_summary_query:
            for i, cat in enumerate(['total', 'ongoing', 'completed', 'pm_launched', 'pm_ongoing', 'pm_completed'], 2):
                if row[i] > 0:
                    state_summary_interactive[row.state][cat]['count'] += row[i]
                    state_summary_interactive[row.state][cat]['phases'][row.rusa_phase] += row[i]
        
        for state, categories in state_summary_interactive.items():
            for cat, data in categories.items():
                state_summary_interactive[state][cat]['phases'] = dict(sorted(data['phases'].items()))

        summary_data['state_summary_interactive'] = dict(sorted(state_summary_interactive.items()))

        summary_data['state_phase_summary'] = analytics_query.with_entities(State.name.label('state'), RusaPhase.name.label('rusa_phase'), func.count(MprReport.id)).group_by(State.name, RusaPhase.name).order_by(State.name, RusaPhase.name).all()
        summary_data['state_phase_component_summary'] = analytics_query.with_entities(State.name.label('state'), RusaPhase.name.label('rusa_phase'), Component.name.label('component_name'), func.count(MprReport.id)).group_by(State.name, RusaPhase.name, Component.name).order_by(State.name, RusaPhase.name, Component.name).all()
        summary_data['month_year_summary'] = query.with_entities(MprReport.year, MprReport.months, func.count(MprReport.id)).group_by(MprReport.year, MprReport.months).order_by(desc(MprReport.year), desc(month_order)).all()
        
        latest_month_year = MprReport.query.with_entities(MprReport.year, MprReport.months).order_by(desc(MprReport.year), desc(month_order)).first()
        if latest_month_year:
            latest_year, latest_month = latest_month_year
            
            project_key = [
                State.name, RusaPhase.name, Component.name,
                MprReport.institution_name, MprReport.district
            ]

            report_rank_sq = query.with_entities(
                MprReport.id,
                func.row_number().over(
                    partition_by=project_key,
                    order_by=[desc(MprReport.year), desc(month_order)]
                ).label('rn')
            ).subquery()

            latest_reports_q = query.join(
                report_rank_sq, MprReport.id == report_rank_sq.c.id
            ).filter(report_rank_sq.c.rn == 1)

            ongoing_latest_reports_q = latest_reports_q.filter(MprReport.project_status == 'Ongoing')

            missing_reports_q = ongoing_latest_reports_q.filter(
                ~and_(MprReport.year == latest_year, MprReport.months == latest_month)
            )

            total_missing_count = missing_reports_q.count()
            pm_missing_count = missing_reports_q.filter(MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes').count()

            missing_projects_data = []
            # Eager load relationships for the missing projects data
            for report in missing_reports_q.options(contains_eager(MprReport.component_rel)).order_by(*project_key).all():
                missing_projects_data.append({
                    'state': report.state_rel.name if report.state_rel else 'N/A',
                    'rusa_phase': report.rusa_phase_rel.name if report.rusa_phase_rel else 'N/A',
                    'component_name': report.component_rel.name if report.component_rel else 'N/A',
                    'institution_name': report.institution_name,
                    'district': report.district,
                    'last_reported': f'{report.months} {report.year}',
                    'is_pm_launched': report.whether_pm_digitally_launched_project_yes_no_ == 'Yes'
                })
            
            summary_data['missing_ongoing_projects'] = missing_projects_data
            summary_data['missing_total_count'] = total_missing_count
            summary_data['missing_pm_count'] = pm_missing_count
            summary_data['latest_month_for_missing'] = f"{latest_month} {latest_year}"

    filter_options = {
        'states': get_distinct_values(State, State.name),
        'rusa_phases': get_distinct_values(RusaPhase, RusaPhase.name),
        'component_names': get_distinct_values(Component, Component.name),
        'institution_names': get_distinct_values(MprReport, MprReport.institution_name),
        'districts': get_distinct_values(MprReport, MprReport.district),
        'project_statuses': get_distinct_values(MprReport, MprReport.project_status),
        'years': get_distinct_values(MprReport, MprReport.year),
        'months': get_distinct_values(MprReport, MprReport.months),
    }

    return render_template(
        'mpr/records.html',
        pagination=pagination,
        filters=filters,
        filter_options=filter_options,
        summary_data=summary_data,
        is_filtered=any(filters.values())
    )
