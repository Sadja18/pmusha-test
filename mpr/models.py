
from main import db
from sqlalchemy.orm import relationship

# Association table for the many-to-many relationship between RusaPhase and Component
rusa_phase_components = db.Table('rusa_phase_components',
    db.Column('rusa_phase_id', db.Integer, db.ForeignKey('rusa_phases.id'), primary_key=True),
    db.Column('component_id', db.Integer, db.ForeignKey('components.id'), primary_key=True)
)

class State(db.Model):
    __tablename__ = 'states'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    reports = relationship("MprReport", back_populates="state_rel", foreign_keys="MprReport.state_id")

class RusaPhase(db.Model):
    __tablename__ = 'rusa_phases'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    reports = relationship("MprReport", back_populates="rusa_phase_rel", foreign_keys="MprReport.rusa_phase_id")
    # Many-to-many relationship with Component
    components = relationship('Component', secondary=rusa_phase_components, back_populates='rusa_phases')

class Component(db.Model):
    __tablename__ = 'components'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    reports = relationship("MprReport", back_populates="component_rel", foreign_keys="MprReport.component_id")
    rusa_phases = relationship('RusaPhase', secondary=rusa_phase_components, back_populates='components')

class MprReport(db.Model):
    __tablename__ = 'mpr_report'
    id = db.Column(db.Integer, primary_key=True)
    
    # --- String columns for migration ---
    state = db.Column(db.String(255), nullable=True)
    rusa_phase = db.Column(db.String(255), nullable=True)

    # --- Foreign key columns ---
    state_id = db.Column(db.Integer, db.ForeignKey('states.id'), nullable=True)
    rusa_phase_id = db.Column(db.Integer, db.ForeignKey('rusa_phases.id'), nullable=True)
    component_id = db.Column(db.Integer, db.ForeignKey('components.id'), nullable=True)

    # --- Relationships ---
    state_rel = relationship('State', back_populates='reports', foreign_keys=[state_id])
    rusa_phase_rel = relationship('RusaPhase', back_populates='reports', foreign_keys=[rusa_phase_id])
    component_rel = relationship('Component', back_populates='reports', foreign_keys=[component_id])

    months = db.Column(db.String(255), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    institution_name = db.Column(db.String(255), nullable=True)
    aishe_code = db.Column(db.String(255), nullable=True)
    district = db.Column(db.String(255), nullable=True)
    pab_meeting_number = db.Column(db.String(255), nullable=True)
    pab_date = db.Column(db.DateTime, nullable=True)
    central_share_approved = db.Column(db.Float, nullable=True)
    central_share_released = db.Column(db.Float, nullable=True)
    central_share_utilised = db.Column(db.Float, nullable=True)
    state_share_approved = db.Column(db.Integer, nullable=True)
    state_share_released = db.Column(db.Float, nullable=True)
    state_share_utilised = db.Column(db.Float, nullable=True)
    total_amount_approved = db.Column(db.Float, nullable=True)
    total_amount_released = db.Column(db.Float, nullable=True)
    total_amount_utilised = db.Column(db.Float, nullable=True)
    activities_that_have_been_already_undertaken_in_current_month = db.Column(db.Text, nullable=True)
    activities_that_have_been_undertaken_till_previous_month = db.Column(db.Text, nullable=True)
    activities_yet_to_be_undertaken = db.Column(db.Text, nullable=True)
    percentage_physical_progress_total = db.Column(db.Float, nullable=True)
    whether_pm_digitally_launched_project_yes_no_ = db.Column(db.String(255), nullable=True)
    project_inauguration_status_inaugurated_not_inaugurated_ = db.Column(db.String(255), nullable=True)
    if_inaugurated_then_by_whom_and_when = db.Column(db.String(255), nullable=True)
    tentative_date_of_completion = db.Column(db.DateTime, nullable=True)
    project_status = db.Column(db.String(255), nullable=True)
    if_project_is_completed_whether_the_project_is_functional_or_lying_idle_not_functional_ = db.Column(db.String(255), nullable=True)
    if_the_project_is_completed_but_not_functional_please_state_the_reason_s_ = db.Column(db.Text, nullable=True)
    benfits_from_the_projects_please_provide_details_ = db.Column(db.Text, nullable=True)
    number_of_students_benefitted = db.Column(db.Float, nullable=True)
    number_of_faculties_benefitted = db.Column(db.Float, nullable=True)
    number_of_research_works_being_undertaken = db.Column(db.Float, nullable=True)
    physical_inspection_reports_pir_ = db.Column(db.String(255), nullable=True)
    pir_uploaded_yes_no_not_selected_ = db.Column(db.String(255), nullable=True)
