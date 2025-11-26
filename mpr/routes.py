
from flask import render_template, request
from sqlalchemy import desc, case, func, and_
from . import mpr_bp
from main import cache
from .models import MprReport
from collections import defaultdict

def get_distinct_values(column, query=None):
    """Helper function to get distinct, non-empty values for a column, optionally from a pre-filtered query."""
    if query is None:
        query = MprReport.query
    return [
        r[0] for r in query.with_entities(column).distinct().filter(column.isnot(None), column != '').order_by(column).all()
    ]

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

    base_query = MprReport.query

    # Apply filters to the query
    if filters['state']:
        base_query = base_query.filter(MprReport.state.in_(filters['state']))
    if filters['rusa_phase']:
        base_query = base_query.filter(MprReport.rusa_phase.in_(filters['rusa_phase']))
    if filters['component_name']:
        base_query = base_query.filter(MprReport.component_name.in_(filters['component_name']))
    if filters['institution_name']:
        base_query = base_query.filter(MprReport.institution_name.in_(filters['institution_name']))
    if filters['district']:
        base_query = base_query.filter(MprReport.district.in_(filters['district']))
    if filters['project_status']:
        base_query = base_query.filter(MprReport.project_status.in_(filters['project_status']))
    if filters['year']:
        base_query = base_query.filter(func.cast(MprReport.year, func.String).in_(filters['year']))
    if filters['months']:
        base_query = base_query.filter(MprReport.months.in_(filters['months']))

    month_order = case(
        {'December': 12, 'November': 11, 'October': 10, 'September': 9, 'August': 8, 'July': 7, 'June': 6, 'May': 5, 'April': 4, 'March': 3, 'February': 2, 'January': 1},
        value=MprReport.months, else_=0
    )

    sorted_query = base_query.order_by(
        desc(MprReport.year), desc(month_order), MprReport.state, MprReport.rusa_phase
    )

    pagination = sorted_query.paginate(page=page, per_page=per_page, error_out=False)

    summary_data = {}
    filtered_records_exist = base_query.first() is not None

    if filtered_records_exist:
        # Interactive State-wise summary with RUSA phase drilldown
        interactive_summary_query = base_query.with_entities(
            MprReport.state,
            MprReport.rusa_phase,
            func.count(MprReport.id).label('total'),
            func.sum(case((MprReport.project_status == 'Ongoing', 1), else_=0)).label('ongoing'),
            func.sum(case((MprReport.project_status == 'Completed', 1), else_=0)).label('completed'),
            func.sum(case((MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', 1), else_=0)).label('pm_launched'),
            func.sum(case((and_(MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', MprReport.project_status == 'Ongoing'), 1), else_=0)).label('pm_ongoing'),
            func.sum(case((and_(MprReport.whether_pm_digitally_launched_project_yes_no_ == 'Yes', MprReport.project_status == 'Completed'), 1), else_=0)).label('pm_completed')
        ).group_by(MprReport.state, MprReport.rusa_phase).order_by(MprReport.state, MprReport.rusa_phase).all()

        state_summary_interactive = defaultdict(lambda: { 
            cat: {'count': 0, 'phases': defaultdict(int)} for cat in ['total', 'ongoing', 'completed', 'pm_launched', 'pm_ongoing', 'pm_completed']
        })

        for row in interactive_summary_query:
            for i, cat in enumerate(['total', 'ongoing', 'completed', 'pm_launched', 'pm_ongoing', 'pm_completed'], 2):
                if row[i] > 0:
                    state_summary_interactive[row.state][cat]['count'] += row[i]
                    state_summary_interactive[row.state][cat]['phases'][row.rusa_phase] += row[i]
        
        # Sort the inner phase dictionaries by phase name for consistent order
        for state, categories in state_summary_interactive.items():
            for cat, data in categories.items():
                state_summary_interactive[state][cat]['phases'] = dict(sorted(data['phases'].items()))

        summary_data['state_summary_interactive'] = dict(sorted(state_summary_interactive.items()))

        summary_data['state_phase_summary'] = base_query.with_entities(MprReport.state, MprReport.rusa_phase, func.count(MprReport.id)).group_by(MprReport.state, MprReport.rusa_phase).order_by(MprReport.state, MprReport.rusa_phase).all()
        summary_data['state_phase_component_summary'] = base_query.with_entities(MprReport.state, MprReport.rusa_phase, MprReport.component_name, func.count(MprReport.id)).group_by(MprReport.state, MprReport.rusa_phase, MprReport.component_name).order_by(MprReport.state, MprReport.rusa_phase, MprReport.component_name).all()
        summary_data['month_year_summary'] = base_query.with_entities(MprReport.year, MprReport.months, func.count(MprReport.id)).group_by(MprReport.year, MprReport.months).order_by(desc(MprReport.year), desc(month_order)).all()
        
        latest_month_year = base_query.with_entities(MprReport.year, MprReport.months).order_by(desc(MprReport.year), desc(month_order)).first()
        if latest_month_year:
            latest_year, latest_month = latest_month_year
            ongoing_projects_query = base_query.filter(MprReport.project_status == 'Ongoing')
            all_ongoing_institutions = {r.institution_name for r in ongoing_projects_query.distinct(MprReport.institution_name).all()}
            reported_in_latest_month = {r.institution_name for r in ongoing_projects_query.filter(MprReport.year == latest_year, MprReport.months == latest_month).all()}
            missing_projects = all_ongoing_institutions - reported_in_latest_month
            summary_data['missing_ongoing_projects'] = sorted(list(missing_projects))
            summary_data['latest_month_for_missing'] = f"{latest_month} {latest_year}"

    filter_options = {
        'states': get_distinct_values(MprReport.state),
        'rusa_phases': get_distinct_values(MprReport.rusa_phase),
        'component_names': get_distinct_values(MprReport.component_name),
        'institution_names': get_distinct_values(MprReport.institution_name),
        'districts': get_distinct_values(MprReport.district),
        'project_statuses': get_distinct_values(MprReport.project_status),
        'years': get_distinct_values(MprReport.year),
        'months': get_distinct_values(MprReport.months),
    }

    return render_template(
        'mpr/records.html',
        pagination=pagination,
        filters=filters,
        filter_options=filter_options,
        summary_data=summary_data
    )
