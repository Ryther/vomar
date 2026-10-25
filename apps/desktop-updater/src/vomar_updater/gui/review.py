"""One protected-focus review: visible decision, optional details, fresh challenge."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QDialogButtonBox,QCheckBox,QPushButton,QPlainTextEdit,QScrollArea,QWidget

NAMES={'update':'Bluetooth update','prepare':'Prepare legacy recovery','trial':'Bluetooth qualification trial','first-install':'First installation','repair':'Repair interrupted installation','start':'Start verified firmware','halt':'Halt selected DK target','bench-first-install':'Candidate bench installation','bench-repair':'Candidate bench repair','bench-start':'Candidate bench start','zigbee':'Zigbee update','fleet':'Device batch','operator-confirm':'Confirm physical operation'}

class ReviewDialog(QDialog):
    def __init__(self,result,parent=None):
        super().__init__(parent);self.setWindowTitle('Review '+NAMES.get(result['operation'],result['operation']));self.resize(620,560);self.setMinimumWidth(460)
        layout=QVBoxLayout(self);layout.setSpacing(16);title=QLabel(NAMES.get(result['operation'],result['operation']));title.setProperty('heading',True);layout.addWidget(title)
        info=QLabel(result['message']);info.setWordWrap(True);layout.addWidget(info)
        scroll=QScrollArea();scroll.setWidgetResizable(True);panel=QWidget();form=QFormLayout(panel);summary=result['summary']
        visible=summary.get('review',summary)
        for key,value in visible.items():
            if key in ('package','family','body','installed','original','journal_head','token','observed_json','generation','expires','package_digest','export_path','resume_session','resume_role','journal_head','binding_json','snapshot'):continue
            label=QLabel(str(value) if not isinstance(value,(dict,list)) else json.dumps(value,ensure_ascii=False));label.setWordWrap(True);label.setTextInteractionFlags(Qt.TextSelectableByMouse|Qt.TextSelectableByKeyboard);form.addRow(key.replace('_',' ').capitalize(),label)
        scroll.setWidget(panel);layout.addWidget(scroll,1)
        details=QPlainTextEdit(json.dumps(summary,indent=2,ensure_ascii=False));details.setReadOnly(True);details.setMaximumHeight(170);details.hide();toggle=QPushButton('Technical details');toggle.setCheckable(True);toggle.toggled.connect(details.setVisible);layout.addWidget(toggle);layout.addWidget(details)
        self.physical=QCheckBox('I confirmed the Vimar 30805 label and isolated the target from mains')
        needs_physical=result['operation'] in ('first-install','bench-first-install','bench-repair','bench-start','repair','start');self.physical.setVisible(needs_physical);layout.addWidget(self.physical)
        label=QLabel('Type '+result['challenge']+' to approve only this operation');label.setWordWrap(True);layout.addWidget(label);self.challenge=QLineEdit();self.challenge.setAccessibleName('Operation approval challenge');layout.addWidget(self.challenge)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.approve=buttons.button(QDialogButtonBox.Ok);self.approve.setText('Approve operation');self.approve.setEnabled(False);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        def validate():self.approve.setEnabled(self.challenge.text()==result['challenge'] and (not needs_physical or self.physical.isChecked()))
        self.challenge.textChanged.connect(validate);self.physical.toggled.connect(validate);self.challenge.setFocus()
