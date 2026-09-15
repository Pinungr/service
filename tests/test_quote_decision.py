from datetime import date, timedelta
import pytest
from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton
from repairshop.domain import RuleError
from repairshop import services
from repairshop.ui import MainWindow
from test_lifecycle import route, diagnosis


def estimate(service, customer, monkeypatch=None):
    job, life=route(service,customer);diagnosis(life,job)
    if monkeypatch:
        # The shop's own date is the single source of truth for business days, so that
        # is what a historical quotation has to be issued against.
        with monkeypatch.context() as patch:
            patch.setattr(services,'today',lambda:'1900-02-01')
            q=service.issue_quote(job,'Repair board',[dict(description='Labour',amount=50000)],valid_until='1900-02-09')
    else:q=service.issue_quote(job,'Repair board',[dict(description='Labour',amount=50000)])
    return job,q,life


def test_past_expiry_cannot_issue_or_replace_current_quote(service,customer):
    job,q,_=estimate(service,customer)
    for expiry in ('1900-02-09',(date.today()-timedelta(days=1)).isoformat()):
        with pytest.raises(RuleError,match='expiry cannot be in the past'):
            service.issue_quote(job,'Bad date',[dict(description='Labour',amount=50000)],valid_until=expiry)
    assert service.db.one('SELECT count(*) n FROM quotes')['n']==1
    assert service.db.one('SELECT state FROM quotes WHERE id=?',(q,))['state']=='issued'


def test_expired_quote_can_be_declined_but_never_approved(service,customer,monkeypatch):
    job,q,life=estimate(service,customer,monkeypatch)
    assert service.quote_decision_details(q)['expired']
    assert any('Quotation expired' in a for a in life.snapshot(job)['attention'])
    with pytest.raises(RuleError,match='expired on 1900-02-09'):
        service.decide_quote(q,'approved','Test customer','call')
    assert not service.db.rows('SELECT * FROM decisions')
    service.decide_quote(q,'declined','Test customer','call','Does not want repair')
    assert service.job(job)['stage']=='return_unrepaired'
    assert service.db.one('SELECT decision FROM decisions')['decision']=='declined'
    assert service.db.one('SELECT valid_until FROM quotes WHERE id=?',(q,))['valid_until']=='1900-02-09'
    with pytest.raises(RuleError,match='already declined'):
        service.decide_quote(q,'approved','Test customer','call')


@pytest.mark.parametrize('expiry',[None,'today'])
def test_current_quote_with_no_expiry_or_today_accepts_approval(service,customer,expiry):
    job,_,_=estimate(service,customer)
    q=service.issue_quote(job,'Repair',[dict(description='Labour',amount=50000)],valid_until=date.today().isoformat() if expiry else None)
    assert not service.quote_decision_details(q)['expired']
    service.decide_quote(q,'approved','Test customer','in_person')
    assert service.job(job)['stage']=='approved'


def test_old_or_changed_quote_cannot_accept_a_decision(service,customer):
    job,q,life=estimate(service,customer)
    q2=service.issue_quote(job,'Revised repair',[dict(description='Labour',amount=60000)])
    for action in (lambda:service.quote_decision_details(q),lambda:service.decide_quote(q,'declined','Test customer','call')):
        with pytest.raises(RuleError,match='current version 2'):action()
    assert not service.db.rows('SELECT * FROM decisions')
    life.execute(job,'decline',dict(notes='Customer cancelled before deciding'))
    with pytest.raises(RuleError,match='no longer waiting'):service.quote_decision_details(q2)


def test_expired_decision_dialog_shows_date_and_records_decline(qtbot,service,customer,monkeypatch):
    job,q,_=estimate(service,customer,monkeypatch)
    w=MainWindow(service);qtbot.addWidget(w)
    def act():
        d=QApplication.activeModalWidget()
        try:
            text=' '.join(label.text() for label in d.findChildren(QLabel))
            assert 'EXPIRED on 09 Feb 1900' in text
            choice=d.fields['decision'];assert choice.count()==1 and choice.currentData()=='declined'
            assert not choice.isEditable()
            assert any(b.text()=='Issue revised quotation' for b in d.findChildren(QPushButton))
            d.fields['person'].setText('Test customer')
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,act);w.decision_form(dict(id=q))
    assert service.job(job)['stage']=='return_unrepaired'


def test_quote_expiry_is_explicit_and_revision_preserves_charges(qtbot,service,customer):
    job,q,_=estimate(service,customer)
    w=MainWindow(service);qtbot.addWidget(w)
    def without_expiry():
        d=QApplication.activeModalWidget()
        try:
            assert not d.fields['has_expiry'].isChecked()
            assert not d.fields['valid_until'].isEnabled()
            assert d.fields['valid_until'].date()>=QDate.currentDate()
            d.fields['scope'].setPlainText('No expiry estimate')
            d.fields['lines'].setPlainText('Labour | 500.00')
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,without_expiry);w.quote_form(job)
    row=service.db.one('SELECT * FROM quotes ORDER BY id DESC LIMIT 1')
    assert row['valid_until'] is None and row['total']==50000
    def with_expiry():
        d=QApplication.activeModalWidget()
        try:
            assert d.fields['scope'].toPlainText()=='No expiry estimate'
            assert d.fields['lines'].toPlainText()=='Labour | 500'
            d.fields['has_expiry'].setChecked(True)
            assert d.fields['valid_until'].isEnabled()
            d.fields['valid_until'].setDate(QDate.currentDate())
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,with_expiry);w.quote_form(job,source=row)
    latest=service.db.one('SELECT * FROM quotes ORDER BY id DESC LIMIT 1')
    assert latest['valid_until']==date.today().isoformat() and latest['total']==50000
    assert service.db.one('SELECT state FROM quotes WHERE id=?',(row['id'],))['state']=='superseded'
