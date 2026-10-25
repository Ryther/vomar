import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication
from vomar_updater.gui.app import Window,theme

class Worker(QObject):
    result=Signal(str,str);failure=Signal(str,str);progress_event=Signal(str);ready=Signal()
    def submit(self,*a):pass
    def stop(self):self.stopped=True
    def close(self):pass
    def wait(self,*a):return True


def test_native_navigation_keyboard_and_stop():
    app=QApplication.instance() or QApplication([]);theme(app,'light');w=Worker();window=Window(w);window.show();app.processEvents()
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
