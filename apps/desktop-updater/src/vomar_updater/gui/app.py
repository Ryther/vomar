"""Native Qt Widgets presentation over one owned application worker."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from PySide6.QtCore import QThread,Signal,Qt,QTimer
from PySide6.QtGui import QAction,QColor,QPalette,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QStackedWidget,QTreeWidget,QTreeWidgetItem,QLineEdit,QComboBox,QFileDialog,QMessageBox,QInputDialog,QProgressBar,QScrollArea,QGroupBox,QCheckBox)
from vomar_updater.service import Service


class Worker(QThread):
    def __init__(self,state=None):super().__init__();self.state=state
    result=Signal(str,str);failure=Signal(str,str);progress_event=Signal(str);ready=Signal()
    def run(self):
        self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
        if sys.platform=='win32':
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        self.service=Service(self.state,on_event=lambda e:self.progress_event.emit(json.dumps(e)));self.tasks=set();self.ready.emit();self.loop.run_forever();self.loop.close()
    def submit(self,action,args=None):
        async def command():
            try:self.result.emit(action,json.dumps(await self.service.dispatch(action,args)))
            except BaseException as e:self.failure.emit(action,str(e) or type(e).__name__)
        def schedule():
            task=self.loop.create_task(command());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        self.loop.call_soon_threadsafe(schedule)
    def stop(self):
        if hasattr(self,'service'):self.service.stop()
    def close(self):
        self.stop()
        if hasattr(self,'loop'):
            async def shutdown():
                if self.tasks:await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
                await self.service.close();self.loop.stop()
            asyncio.run_coroutine_threadsafe(shutdown(),self.loop)


def theme(app,value):
    dark=value=='dark' or value=='system' and app.styleHints().colorScheme()==Qt.ColorScheme.Dark
    colors=('#1B1E22','#252A30','#F0EEE9','#BFC3C6','#FFA15A','#331806') if dark else ('#FAF8F3','#EFEEE8','#25282C','#565E65','#A64412','#FFF8F2')
    surface,panel,text,secondary,accent,on_accent=colors;p=QPalette()
    for role,color in [(QPalette.Window,surface),(QPalette.Base,surface),(QPalette.AlternateBase,panel),(QPalette.WindowText,text),(QPalette.Text,text),(QPalette.Button,panel),(QPalette.ButtonText,text),(QPalette.Highlight,accent),(QPalette.HighlightedText,on_accent),(QPalette.PlaceholderText,secondary)]:p.setColor(role,QColor(color))
    app.setPalette(p)
    app.setStyleSheet(f'QWidget{{font-size:16px;}} QPushButton{{min-height:36px;padding:2px 12px;}} QLineEdit,QComboBox{{min-height:34px;}} QPushButton:focus,QLineEdit:focus,QComboBox:focus,QTreeWidget:focus{{border:2px solid {accent};}} QPushButton:checked{{background:{accent};color:{on_accent};}} QLabel[heading="true"]{{font-size:24px;font-weight:600;}}')


class Window(QMainWindow):
    def __init__(self,worker=None):
        super().__init__();self.setWindowTitle('Vomar');self.resize(1080,720);self.setMinimumSize(760,560);self.worker=worker or Worker();self.busy=False;self.device_rows=[];self.scanned=[];self.selected_session=None
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(20,20,20,16);outer.setSpacing(16)
        header=QHBoxLayout();brand=QLabel('Vomar');brand.setProperty('heading',True);header.addWidget(brand);header.addStretch();self.status=QLabel('Opening private application state…');self.status.setWordWrap(True);self.status.setAccessibleName('Operation status');header.addWidget(self.status,1)
        self.stop_button=QPushButton('Stop');self.stop_button.setAccessibleName('Stop the current operation');self.stop_button.clicked.connect(self.stop);self.stop_button.setEnabled(False);header.addWidget(self.stop_button);outer.addLayout(header)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.hide();outer.addWidget(self.progress)
        body=QHBoxLayout();nav=QVBoxLayout();nav.setSpacing(8);self.stack=QStackedWidget();self.nav=[]
        for i,name in enumerate(('Devices','Activity','Settings')):
            button=QPushButton(name);button.setCheckable(True);button.clicked.connect(lambda _,i=i:self.navigate(i));nav.addWidget(button);self.nav.append(button)
        nav.addStretch();body.addLayout(nav);body.addWidget(self.stack,1);outer.addLayout(body,1)
        self.build_devices();self.build_activity();self.build_settings();self.navigate(0)
        self.worker.result.connect(self.result);self.worker.failure.connect(self.failure);self.worker.progress_event.connect(self.handle_event);self.worker.ready.connect(self.initialized)
        action=QAction('Stop',self);action.setShortcut(QKeySequence('Esc'));action.triggered.connect(self.stop);self.addAction(action)
        if worker is None:self.worker.start()
    def heading(self,text,layout):
        label=QLabel(text);label.setProperty('heading',True);layout.addWidget(label)
    def button(self,label,callback,layout):
        b=QPushButton(label);b.clicked.connect(callback);layout.addWidget(b);return b
    def field(self,label,layout,value='',password=False):
        f=QLineEdit(value);f.setAccessibleName(label);f.setPlaceholderText(label)
        if password:f.setEchoMode(QLineEdit.Password)
        layout.addRow(label,f);return f
    def navigate(self,index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.nav):b.setChecked(i==index)
        if hasattr(self.worker,'loop'):
            if index==0:self.worker.submit('devices.list')
            if index==1:self.worker.submit('sessions.list')
    def initialized(self):self.status.setText('Choose a signed release or discover a nearby dimmer.');self.worker.submit('devices.list');self.worker.submit('settings.get')
    def send(self,action,args=None):
        if self.busy:QMessageBox.information(self,'Operation in progress','Stop or finish the current operation before starting another.');return
        self.active_action=action;self.busy=True;self.stop_button.setEnabled(True);self.status.setText('Working…');self.progress.setRange(0,0);self.progress.show();self.worker.submit(action,args)
    def stop(self):self.worker.stop();self.status.setText('Stop requested. Preserved sessions may require explicit review.');self.stop_button.setEnabled(False)
    def choose_file(self,action,title,save=False):
        path=(QFileDialog.getSaveFileName(self,title,'','ZIP or JSON (*)') if save else QFileDialog.getOpenFileName(self,title,'','ZIP or JSON (*)'))[0]
        if path:self.send(action,{'path':path})
    def build_devices(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(20,0,0,0);self.heading('Devices',layout)
        help=QLabel('Find a dimmer nearby or import your saved list. Names and rooms are optional.');help.setWordWrap(True);layout.addWidget(help)
        controls=QHBoxLayout();self.button('Find with Bluetooth',lambda:self.send('devices.scan'),controls);self.button('Import list',lambda:self.choose_file('devices.import','Import device registry'),controls);controls.addStretch();layout.addLayout(controls)
        self.devices=QTreeWidget();self.devices.setHeaderLabels(['Name','Room','Connection']);self.devices.setRootIsDecorated(False);self.devices.setSelectionMode(QTreeWidget.ExtendedSelection);self.devices.setAccessibleName('Saved devices');self.devices.itemSelectionChanged.connect(self.select_device);layout.addWidget(self.devices,1)
        self.empty=QLabel('No saved devices. Use Bluetooth discovery to choose a device, then give it a name.');self.empty.setWordWrap(True);layout.addWidget(self.empty)
        row=QHBoxLayout();self.button('Name or move',self.edit_device,row);self.button('Remove',self.remove_device,row);row.addStretch();layout.addLayout(row)
        form=QFormLayout();self.target=self.field('Bluetooth target',form);self.zigbee_network=self.field('Zigbee network',form);self.zigbee_ieee=self.field('Zigbee device',form);self.carrier=self.field('HTTPS OTA source',form);layout.addLayout(form)
        row=QHBoxLayout();self.button('Review Bluetooth update',lambda:self.send('updates.preview',{'target':self.target.text()}),row);self.button('Review selected batch',self.review_batch,row);self.button('Read recovery history',lambda:self.send('diagnostics.read',{'target':self.target.text()}),row);layout.addLayout(row)
        self.button('Review Zigbee update',lambda:self.send('zigbee.preview',{'network':self.zigbee_network.text(),'ieee':self.zigbee_ieee.text(),'source':self.carrier.text()}),layout)
        self.stack.addWidget(page)
    def review_batch(self):
        transport,ok=QInputDialog.getItem(self,'Batch connection','Connection',['auto','ble','zigbee'],0,False)
        if not ok:return
        mode,ok=QInputDialog.getItem(self,'Batch scheduling','Scheduling',['sequential','network-parallel'],0,False)
        if ok:self.send('fleet.preview',{'ids':[r.data(0,Qt.UserRole)['id'] for r in self.devices.selectedItems()],'mode':mode,'transport':transport,'source':self.carrier.text()})
    def resume_batch(self):
        batch,ok=QInputDialog.getText(self,'Review paused batch','Batch ID (from activity details)')
        if ok:self.send('fleet.resume-preview',{'batch':batch})
    def select_device(self):
        rows=self.devices.selectedItems()
        if rows:self.target.setText(rows[0].data(0,Qt.UserRole).get('ble',''))
    def edit_device(self):
        rows=self.devices.selectedItems()
        if not rows:return
        r=rows[0].data(0,Qt.UserRole);name,ok=QInputDialog.getText(self,'Device name','Name',text=r['name'])
        if not ok:return
        room,ok=QInputDialog.getText(self,'Room','Room (optional)',text=r['room'])
        if ok:self.send('devices.save',{**r,'target':r['ble'],'name':name,'room':room})
    def remove_device(self):
        rows=self.devices.selectedItems()
        if rows:self.send('devices.remove',{'id':rows[0].data(0,Qt.UserRole)['id']})
    def build_activity(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(20,0,0,0);self.heading('Activity',layout)
        self.activity=QTreeWidget();self.activity.setHeaderLabels(['Operation','Status','Started']);self.activity.setAccessibleName('Durable operation sessions');self.activity.itemSelectionChanged.connect(self.select_session);layout.addWidget(self.activity,1)
        self.activity_help=QLabel('Interrupted operations stay here. Restarting Vomar never approves a continuation.');self.activity_help.setWordWrap(True);layout.addWidget(self.activity_help)
        row=QHBoxLayout();self.button('Refresh',lambda:self.send('sessions.list'),row);self.button('Show batches',lambda:self.send('fleet.list'),row);self.button('Review paused batch',self.resume_batch,row);self.button('Review interrupted Bluetooth update',lambda:self.send('updates.resume-preview',{'session':self.selected_session}),row);self.button('Confirm physical operation',lambda:self.send('sessions.confirm',{'session':self.selected_session}),row);layout.addLayout(row);self.stack.addWidget(page)
    def select_session(self):
        rows=self.activity.selectedItems()
        if rows:self.selected_session=rows[0].data(0,Qt.UserRole)
    def build_settings(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);page=QWidget();scroll.setWidget(page);layout=QVBoxLayout(page);layout.setContentsMargins(20,0,0,0);layout.setSpacing(20);self.heading('Settings',layout)
        updates=QGroupBox('Updates');u=QVBoxLayout(updates);self.release_label=QLabel('No verified release selected');self.release_label.setWordWrap(True);u.addWidget(self.release_label);form=QFormLayout();self.source=self.field('GitHub repository',form,'Ryther/vomar');u.addLayout(form)
        row=QHBoxLayout();self.button('Check latest release',lambda:self.send('releases.latest',{'repository':self.source.text()}),row);self.button('Choose signed ZIP',lambda:self.choose_file('releases.inspect','Choose signed firmware ZIP'),row);u.addLayout(row);layout.addWidget(updates)
        appearance=QGroupBox('Appearance');f=QFormLayout(appearance);self.theme=QComboBox();self.theme.addItems(['system','light','dark']);self.theme.setAccessibleName('Theme');self.theme.currentTextChanged.connect(self.change_theme);f.addRow('Theme',self.theme);layout.addWidget(appearance)
        mqtt=QGroupBox('MQTT (optional)');form=QFormLayout(mqtt);self.broker=self.field('Broker address',form);self.username=self.field('Username',form);self.password=self.field('Password',form,password=True);self.topics=[self.field('Topic '+str(i+1),form,'zigbee2mqtt' if i==0 else '') for i in range(3)];self.plain=QCheckBox('Allow this unencrypted local-network connection');form.addRow(self.plain)
        row=QHBoxLayout();self.button('Save connection',self.save_mqtt,row);self.button('Connect',lambda:self.send('mqtt.connect'),row);self.button('Disconnect',lambda:self.send('mqtt.disconnect'),row);form.addRow(row);self.button('Show discovered Zigbee devices',lambda:self.send('mqtt.devices'),form);layout.addWidget(mqtt)
        tools=QGroupBox('Tools');t=QVBoxLayout(tools);form=QFormLayout();self.serial=self.field('DK serial number',form);t.addLayout(form)
        self.tools_help=QLabel('Use an isolated, unpowered mains bench. MCU identity does not prove the commercial model. Review the exact physical target before allowing HALT or FLASH writes.');self.tools_help.setWordWrap(True);t.addWidget(self.tools_help)
        self.button('Review DK halt',lambda:self.send('probe.inspect',{'serial':self.serial.text()}),t)
        self.button('Capture and export original',lambda:self.choose_file('backup.capture','Export protected original',save=True),t)
        self.button('Reopen protected original',lambda:self.choose_file('backup.import','Reopen protected original'),t)
        self.button('Choose Bluetooth trial candidate',lambda:self.choose_file('trial.inspect','Choose qualification candidate'),t)
        self.button('Review candidate bench halt',lambda:self.send('probe.inspect',{'serial':self.serial.text(),'candidate':True}),t)
        self.button('Review candidate bench installation',lambda:self.send('bench.preview'),t)
        self.button('Review candidate bench repair',lambda:self.send('bench.repair-preview',{'session':self.selected_session}),t)
        self.button('Review candidate bench start',lambda:self.send('bench.start-preview'),t)
        self.button('Review Bluetooth trial',lambda:self.send('trial.preview',{'target':self.target.text()}),t)
        self.button('Prepare legacy recovery',lambda:self.send('updates.prepare-preview',{'target':self.target.text()}),t)
        self.button('Review first installation',lambda:self.send('first-install.preview'),t)
        self.button('Review interrupted installation repair',lambda:self.send('repair.preview',{'session':self.selected_session}),t)
        self.button('Review verified start',lambda:self.send('start.preview'),t)
        self.button('Export diagnostic report',lambda:self.choose_file('diagnostics.export','Export private diagnostic report',save=True),t)
        layout.addWidget(tools);layout.addStretch();self.stack.addWidget(scroll)
    def change_theme(self,value):
        theme(QApplication.instance(),value)
        if hasattr(self.worker,'loop'):self.worker.submit('settings.save',{'theme':value})
    def save_mqtt(self):
        topics=[t.text() for t in self.topics if t.text()]
        self.send('mqtt.save',{'uri':self.broker.text(),'username':self.username.text(),'password':self.password.text(),'allow_plaintext':self.plain.isChecked(),'networks':[{'id':f'network-{i+1}','label':f'Network {i+1}','topic':v} for i,v in enumerate(topics)]})
    def review(self,result):
        from .review import ReviewDialog
        dialog=ReviewDialog(result,self)
        if dialog.exec()==dialog.DialogCode.Accepted:self.send('execute',{'review':result['review']})
        else:self.worker.submit('review.cancel',{'review':result['review']})
    def result(self,action,raw):
        result=json.loads(raw)
        if action==getattr(self,'active_action',None):
            self.busy=False;self.stop_button.setEnabled(False);self.progress.hide();self.status.setText('Ready')
        if action=='devices.list':
            self.devices.clear();self.device_rows=result;self.empty.setVisible(not result)
            for r in result:
                item=QTreeWidgetItem([r['name'],r['room'],r['ble'] or r['ieee'] or 'No transport assigned']);item.setData(0,Qt.UserRole,r);self.devices.addTopLevelItem(item)
            for i in range(3):self.devices.resizeColumnToContents(i)
        elif action=='devices.scan':
            if not result:self.status.setText('No nearby recovery found. Enable Bluetooth and enter dimmer recovery.');return
            options=[r['name']+' · '+r['id'] for r in result];choice,ok=QInputDialog.getItem(self,'Nearby dimmers','Choose a device',options,0,False)
            if ok:
                r=result[options.index(choice)];self.target.setText(r['id']);name,save=QInputDialog.getText(self,'Save device (optional)','Device name',text=r['name'])
                if save and name:self.send('devices.save',{'name':name,'target':r['id']})
        elif action.startswith('devices.') and action!='devices.list':self.worker.submit('devices.list')
        elif action=='sessions.list':
            import datetime
            self.activity.clear()
            for r in result:
                item=QTreeWidgetItem([r['binding'].get('operation','First installation'),r['phase']+(' · review required' if r['uncertain'] else ''),datetime.datetime.fromtimestamp(r['created']).strftime('%Y-%m-%d %H:%M')]);item.setData(0,Qt.UserRole,r['id']);self.activity.addTopLevelItem(item)
            for i in range(3):self.activity.resizeColumnToContents(i)
        elif action.startswith('releases.'):
            self.release_label.setText('Verified firmware '+result.get('version',result.get('firmware',''))+' · '+result['digest'][:16]);self.status.setText('Signed package verified. Choose a dimmer and review the operation.');self.navigate(0)
        elif action=='settings.get':self.source.setText(result['source']);self.theme.setCurrentText(result['theme'])
        elif action=='trial.inspect':self.status.setText('Qualification candidate verified. Normal release selection is unchanged.')
        elif action=='mqtt.save':self.password.clear();self.status.setText('Connection saved; password is in the OS credential store.')
        elif action=='mqtt.devices':QMessageBox.information(self,'Discovered Zigbee devices',json.dumps(result,indent=2) if result else 'No supported devices observed. Connect to a broker and wait for bridge discovery.')
        elif action=='diagnostics.read':self.status.setText('Recovery history read and saved privately. Export it from Settings → Tools.')
        if isinstance(result,dict) and 'review' in result:self.review(result)
        elif action=='execute':self.status.setText('Operation finished. Check Activity for the exact outcome.');self.worker.submit('sessions.list')
    def failure(self,action,message):
        self.busy=False;self.stop_button.setEnabled(False);self.progress.hide();self.status.setText(message);QMessageBox.warning(self,'Action needs attention',message)
    def handle_event(self,raw):
        event=json.loads(raw);self.status.setText(event.get('message',event.get('phase','Working…')))
        total=event.get('total',0)
        if total:self.progress.setRange(0,100);self.progress.setValue(int(event.get('completed',0)*100/total))
    def closeEvent(self,event):
        self.worker.close()
        if not self.worker.wait(3000):
            event.ignore();self.status.setText('Stopping the owned worker safely. Keep the target connected; close again when it has stopped.');return
        event.accept()


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path);p.add_argument('--smoke-test',action='store_true');p.add_argument('--screenshot',type=Path);args,qt=p.parse_known_args()
    app=QApplication([sys.argv[0],*qt]);app.setApplicationName('Vomar');app.setOrganizationName('OpenVimar');theme(app,'system');worker=Worker(args.state);window=Window(worker);window.show();worker.start()
    if args.smoke_test:
        def finish():
            if args.screenshot:window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(1000,finish)
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
