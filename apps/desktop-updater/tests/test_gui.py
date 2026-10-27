import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication
from vomar_updater.gui.app import Window,theme
import pytest


@pytest.fixture(scope='module', autouse=True)
def owned_application():
    """Keep Qt alive until every test widget has been destroyed."""
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        if shiboken6.isValid(widget):
            widget.close()
            if shiboken6.isValid(widget):
                shiboken6.delete(widget)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

class Worker(QObject):
    result=Signal(str,str);failure=Signal(str,str);progress_event=Signal(str);ready=Signal()
    def submit(self,*a):pass
    def stop(self):self.stopped=True
    def close(self):pass
    def wait(self,*a):return True


def test_native_navigation_keyboard_and_stop():
    app=QApplication.instance() or QApplication([]);theme(app,'light');w=Worker();window=Window(w);window.show();app.processEvents()
    assert not window.windowIcon().isNull()
    assert window.stack.count()==3
    window.nav[2].click();assert window.stack.currentIndex()==2
    window.nav[0].click();assert window.stack.currentIndex()==0
    window.target.setText('opaque-corebluetooth-uuid');window.nav[1].click();window.nav[0].click();assert window.target.text()=='opaque-corebluetooth-uuid'
    window.stop_button.setEnabled(True);window.stop_button.click();assert w.stopped
    window.target.setFocus();app.processEvents();assert app.focusWidget()==window.target
    window.close()


def test_actual_worker_owns_state_and_shuts_down(tmp_path):
    import time
    from vomar_updater.gui.app import Worker as ActualWorker
    app=QApplication.instance() or QApplication([]);worker=ActualWorker(tmp_path/'native state');window=Window(worker);window.show();worker.start();deadline=time.monotonic()+3
    while not hasattr(worker,'service') and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert hasattr(worker,'service')
    worker.submit('devices.list');deadline=time.monotonic()+.1
    while time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    window.close();app.processEvents();assert not worker.isRunning()


def test_review_denial_and_exact_challenge_gate():
    from vomar_updater.gui.review import ReviewDialog
    app=QApplication.instance() or QApplication([])
    d=ReviewDialog({'operation':'first-install','summary':{'Device UID':'00000001:00000002'},'message':'Review exact target','challenge':'00000002'})
    assert not d.approve.isEnabled();d.challenge.setText('wrong');assert not d.approve.isEnabled()
    d.challenge.setText('00000002');assert not d.approve.isEnabled();d.physical.setChecked(True);assert d.approve.isEnabled()
    d.reject();assert d.result()==d.DialogCode.Rejected


def test_gui_process_destroys_widgets_before_application_exit(tmp_path):
    import os,subprocess,sys
    result=subprocess.run([sys.executable,'-X','faulthandler','-m','vomar_updater.gui.app','--state',str(tmp_path/'state'),'--smoke-test','--screenshot',str(tmp_path/'screen.png')],env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'screen.png').stat().st_size>1000


def test_activity_renders_batches_and_offers_explicit_reconciliation(monkeypatch):
    import json
    from PySide6.QtWidgets import QPushButton,QMessageBox
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:None)
    app=QApplication.instance() or QApplication([]);worker=Worker();calls=[];worker.submit=lambda *args:calls.append(args);window=Window(worker)
    group={'id':'batch-fixture','state':'paused','mode':'sequential','jobs':[{'target':'fixture','state':'interrupted','session':'session-fixture'}]}
    window.result('fleet.list',json.dumps([group]))
    assert hasattr(window,'batch_activity') and window.batch_activity.topLevelItemCount()==1
    item=window.batch_activity.topLevelItem(0);window.batch_activity.setCurrentItem(item)
    window.navigate(1)
    buttons={b.text():b for b in window.findChildren(QPushButton)}
    buttons['Review selected batch'].click();assert calls[-1]==('fleet.resume-preview',{'batch':'batch-fixture'})
    window.failure('fleet.resume-preview','Synthetic denial');window.selected_session='session-fixture';buttons['Reconcile Zigbee session'].click()
    assert calls[-1]==('zigbee.reconcile',{'session':'session-fixture'})
    window.close()
