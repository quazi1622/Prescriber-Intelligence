"""Prescriber Intelligence: portable PySide6 desktop dashboard."""
import sys,threading,traceback
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QFileDialog,QMessageBox,QTextEdit,QProgressBar,QHeaderView)
from core import connect,import_rx,import_audit,has_rankings,ranking,choices,write_csv,generate_drafts,available_sheets,DB,DATA
from routing import import_hierarchy
from product_analysis import product_choices,filtered_rankings,has_product_index

CSS="""
QWidget{background:#071b17;color:#d9f7e7;font:12px 'Segoe UI'}
QMainWindow{background:#071b17}
QLabel#title{color:#f0fff5;font-size:27px;font-weight:800}
QLabel#sub{color:#9acbb8;font-size:12px}
QLabel#metric{background:#10382c;border:1px solid #267054;border-radius:11px;padding:16px;color:#c3ffe2;font-size:17px;font-weight:700}
QComboBox,QSpinBox,QTextEdit{background:#113c2f;color:#f1fff5;border:1px solid #348163;border-radius:7px;padding:8px}
QPushButton{background:#187653;color:white;border:1px solid #42a577;border-radius:8px;padding:10px 15px;font-weight:700}
QPushButton:hover{background:#229a70}
QPushButton#red{background:#943748;border:1px solid #d35c6c}
QTableWidget{background:#0e2922;alternate-background-color:#143b2f;gridline-color:#225641;color:#e9fff1}
QHeaderView::section{background:#20563d;color:#d4ffdf;padding:8px;border:0}
QTabBar::tab{background:#113a2b;color:#bbdfca;padding:11px 20px}
QTabBar::tab:selected{background:#2b7653;color:white}
"""
class Signals(QObject):
    done=Signal(int)
    error=Signal(str)
    progress=Signal(int)

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.memory_gb=4
        self.rx_path=None
        self.db=connect(self.memory_gb)
        self.rows=[]
        self.setWindowTitle("Prescriber Intelligence | Emerald Edition")
        self.resize(1450,860)
        outer=QWidget();self.setCentralWidget(outer);root=QVBoxLayout(outer)
        root.setContentsMargins(24,20,24,20);root.setSpacing(14)
        title=QLabel("◆  PRESCRIBER INTELLIGENCE");title.setObjectName("title");root.addWidget(title)
        sub=QLabel("TERRITORY ANALYTICS  •  OFFLINE DUCKDB  •  EMERALD EDITION")
        sub.setObjectName("sub");root.addWidget(sub)
        self.tabs=QTabWidget();root.addWidget(self.tabs)
        analytics=QWidget();self.tabs.addTab(analytics,"◈  ANALYTICS")
        a=QVBoxLayout(analytics)
        filters=QHBoxLayout()
        self.division=QComboBox();self.division.addItems(["ACD","CCD"])
        self.region=QComboBox();self.ase=QComboBox();self.territory=QComboBox()
        self.top=QSpinBox();self.top.setRange(1,20);self.top.setValue(10)
        for label,widget in [("DIVISION",self.division),("RSE / REGION",self.region),("ASE",self.ase),("TERRITORY",self.territory),("TOP N",self.top)]:
            column=QVBoxLayout();column.addWidget(QLabel(label));column.addWidget(widget);filters.addLayout(column)
        a.addLayout(filters)
        product_filters=QHBoxLayout()
        self.generic=QComboBox();self.brand=QComboBox()
        for name,widget in [("GENERIC",self.generic),("BRAND",self.brand)]:
            group=QVBoxLayout()
            group.addWidget(QLabel(name))
            group.addWidget(widget)
            product_filters.addLayout(group)
        a.addLayout(product_filters)
        self.metrics=[]
        stats=QHBoxLayout()
        for _ in range(3):
            label=QLabel("—");label.setObjectName("metric");stats.addWidget(label);self.metrics.append(label)
        a.addLayout(stats)
        actions=QHBoxLayout()
        refresh=QPushButton("↻  REFRESH");refresh.clicked.connect(self.refresh);actions.addWidget(refresh)
        export=QPushButton("↓  EXPORT CSV");export.clicked.connect(self.export);actions.addWidget(export)
        actions.addStretch();a.addLayout(actions)
        self.table=QTableWidget();self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(["RSE","ASE","Territory","#","Doctor Code","Prescriber","Specialty","Rx Count","Product Rows","Address","APP %"])
        self.table.setAlternatingRowColors(True);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(5,245);self.table.setColumnWidth(9,310);a.addWidget(self.table)
        mail=QWidget();self.tabs.addTab(mail,"✉  EMAIL DRAFTS")
        m=QVBoxLayout(mail)
        m.addWidget(QLabel("ACD: RSE TO  •  ASE + ZSI CC  •  MANUAL REVIEW REQUIRED"))
        self.auditlabel=QLabel("Import local recipient audit to activate 51-region draft generation.")
        m.addWidget(self.auditlabel)
        audit=QPushButton("IMPORT ACD RECIPIENT AUDIT CSV");audit.clicked.connect(self.pick_audit);m.addWidget(audit)
        hierarchy=QPushButton("IMPORT ACD RSE–ZSI HIERARCHY EXCEL")
        hierarchy.clicked.connect(self.pick_hierarchy)
        m.addWidget(hierarchy)
        draft=QPushButton("GENERATE ACD .EML DRAFTS");draft.setObjectName("red");draft.clicked.connect(self.drafts);m.addWidget(draft)
        self.recipients=QTableWidget();self.recipients.setColumnCount(5)
        self.recipients.setHorizontalHeaderLabels(["Region","RSE","Email","ASE CC Count","ZSI Email"])
        self.recipients.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);m.addWidget(self.recipients)
        data=QWidget();self.tabs.addTab(data,"▤  DATA / IMPORT")
        d=QVBoxLayout(data)
        d.addWidget(QLabel("Select your Rx workbook locally. Files stay on this computer; no server upload."))
        settings=QHBoxLayout()
        sheetbox=QVBoxLayout();sheetbox.addWidget(QLabel("EXCEL WORKSHEET"))
        self.sheet=QComboBox();self.sheet.setEditable(True)
        self.sheet.addItem("Sheet1")
        sheetbox.addWidget(self.sheet);settings.addLayout(sheetbox)
        memorybox=QVBoxLayout();memorybox.addWidget(QLabel("DUCKDB MEMORY"))
        self.memory=QSpinBox();self.memory.setRange(1,16);self.memory.setValue(4)
        self.memory.setSuffix(" GB");memorybox.addWidget(self.memory);settings.addLayout(memorybox)
        d.addLayout(settings)
        pick=QPushButton("SELECT EXCEL WORKBOOK");pick.clicked.connect(self.pick_rx);d.addWidget(pick)
        self.source_label=QLabel("No Excel workbook selected");d.addWidget(self.source_label)
        importbtn=QPushButton("IMPORT SELECTED WORKSHEET TO DUCKDB")
        importbtn.clicked.connect(self.import_selected);d.addWidget(importbtn)
        self.progress=QProgressBar();d.addWidget(self.progress)
        self.log=QTextEdit();self.log.setReadOnly(True);self.log.setPlainText("Database: "+str(DB));d.addWidget(self.log)
        self.division.currentTextChanged.connect(self.reset_filters)
        self.region.currentTextChanged.connect(self.update_ase)
        self.ase.currentTextChanged.connect(self.update_territory)
        self.territory.currentTextChanged.connect(self.reset_products)
        self.generic.currentTextChanged.connect(self.update_brand)
        self.brand.currentTextChanged.connect(self.refresh)
        self.top.valueChanged.connect(self.refresh)
        self.reset_filters();self.load_audit()
    def selected(self,c):
        return "" if c.currentText() in ("All","") else c.currentText()
    def fill(self,c,values):
        c.blockSignals(True);old=c.currentText();c.clear();c.addItem("All");c.addItems(values)
        if old in values:c.setCurrentText(old)
        c.blockSignals(False)
    def reset_filters(self,*args):
        self.fill(self.region,choices(self.db,self.division.currentText(),"region"))
        self.update_ase()
    def update_ase(self,*args):
        self.fill(self.ase,choices(self.db,self.division.currentText(),"ase",self.selected(self.region)))
        self.update_territory()
    def update_territory(self,*args):
        self.fill(self.territory,choices(self.db,self.division.currentText(),"territory",self.selected(self.region),self.selected(self.ase)))
        self.reset_products()
    def reset_products(self,*args):
        try:
            self.fill(self.generic,product_choices(self.db,self.division.currentText(),
                "generic",self.selected(self.region),self.selected(self.ase),self.selected(self.territory)))
            self.update_brand()
        except Exception as e:self.error(str(e))
    def update_brand(self,*args):
        try:
            self.fill(self.brand,product_choices(self.db,self.division.currentText(),
                "brand",self.selected(self.region),self.selected(self.ase),self.selected(self.territory),
                generic=self.selected(self.generic)))
            self.refresh()
        except Exception as e:self.error(str(e))
    def refresh(self,*args):
        try:
            self.rows=(filtered_rankings(self.db,self.division.currentText(),self.top.value(),
                self.selected(self.region),self.selected(self.ase),self.selected(self.territory),
                self.selected(self.brand),self.selected(self.generic))
                if has_product_index(self.db) else
                [tuple(r)+(None,) for r in ranking(self.db,self.division.currentText(),
                 self.top.value(),self.selected(self.region),self.selected(self.ase),self.selected(self.territory))])
            self.table.setRowCount(len(self.rows))
            for i,row in enumerate(self.rows):
                for j,v in enumerate(row):
                    self.table.setItem(i,j,QTableWidgetItem(str(v if v is not None else "")))
            self.metrics[0].setText(f"{len(self.rows):,}   RANKED PRESCRIBERS")
            self.metrics[1].setText(f"{len({(r[0],r[1],r[2]) for r in self.rows}):,}   TERRITORIES")
            self.metrics[2].setText(f"{sum(int(r[7]) for r in self.rows):,}   PRESCRIPTIONS")
        except Exception as e:self.error(str(e))
    def error(self,message):
        QMessageBox.critical(self,"Prescriber Intelligence",message)
    def export(self):
        if not self.rows:return self.error("Import the prescription workbook first.")
        path,_=QFileDialog.getSaveFileName(self,"Export ranking",str(DATA/"top_prescribers.csv"),"CSV (*.csv)")
        if path:write_csv(self.rows,path)
    def load_audit(self):
        rows=self.db.execute("SELECT region,rse_name,rse_email,ase_emails,zsi_email FROM recipients WHERE division='ACD' ORDER BY region").fetchall()
        self.auditlabel.setText(f"{len(rows)} ACD recipient groups loaded. Review missing addresses before sending.")
        self.recipients.setRowCount(len(rows))
        for i,row in enumerate(rows):
            vals=[row[0],row[1],row[2],len([x for x in (row[3] or "").split(";") if x.strip()]),row[4]]
            for j,val in enumerate(vals):self.recipients.setItem(i,j,QTableWidgetItem(str(val or "")))
    def pick_audit(self):
        path,_=QFileDialog.getOpenFileName(self,"Select ACD recipient audit",str(DATA),"CSV (*.csv)")
        if path:
            try:self.load_audit_after(path)
            except Exception as e:self.error(str(e))
    def load_audit_after(self,path):
        n=import_audit(self.db,path);self.load_audit()
        QMessageBox.information(self,"Imported",f"Loaded {n} ACD groups.")
    def pick_hierarchy(self):
        path,_=QFileDialog.getOpenFileName(
            self,"Select ACD RSE–ZSI hierarchy workbook",str(DATA),"Excel (*.xlsx)")
        if not path:return
        try:
            result=import_hierarchy(self.db,path)
            self.load_audit()
            message=(f"{result['regions']} ACD regions mapped; {result['ready']} ready, "
                     f"{result['blocked']} blocked. Existing ASE lists retained for "
                     f"{result['ase_lists_preserved']} regions.\\n"
                     "Unresolved hierarchy entries will produce blocked, unsendable drafts.")
            self.log.append(message)
            QMessageBox.information(self,"Hierarchy import completed",message)
        except Exception as e:
            self.error(str(e))
    def drafts(self):
        if not has_rankings(self.db):return self.error("Import Rx data first.")
        path=QFileDialog.getExistingDirectory(self,"Draft output folder",str(DATA))
        if not path:return
        try:
            manifest=generate_drafts(self.db,Path(path)/"ACD_drafts",
                self.top.value(),brand=self.selected(self.brand),
                generic=self.selected(self.generic),division="ACD")
            blocked=sum(x[1]=="BLOCKED" for x in manifest)
            QMessageBox.information(self,"Drafts created",f"{len(manifest)} drafts; {blocked} blocked for recipient/data issues.\nNo emails sent.")
        except Exception as e:self.error(str(e))
    def pick_rx(self):
        path,_=QFileDialog.getOpenFileName(self,"Select prescription workbook",str(DATA),"Excel (*.xlsx)")
        if not path:return
        try:
            names=available_sheets(path)
        except Exception as e:
            return self.error("Could not open Excel workbook: "+str(e))
        previous=self.sheet.currentText().strip()
        self.sheet.clear();self.sheet.addItems(names)
        if previous in names:self.sheet.setCurrentText(previous)
        else:self.log.append("Sheet1 not found; choose from: "+", ".join(names))
        self.rx_path=path
        self.source_label.setText("Selected workbook: "+Path(path).name)
        self.log.append("Available worksheets: "+", ".join(names))
    def import_selected(self):
        path=self.rx_path
        if not path:return self.error("Choose an Excel workbook first.")
        selected=self.sheet.currentText().strip()
        if selected not in available_sheets(path):
            return self.error("Worksheet "+repr(selected)+" does not exist in the chosen workbook.")
        answer=QMessageBox.question(self,"Confirm import",
            f"Import worksheet {selected!r} using {self.memory.value()} GB DuckDB memory?\\n"
            "Excel headers and row counts will be validated.\\n"
            "Existing rankings will be preserved if the import fails.")
        if answer!=QMessageBox.Yes:return
        memory=self.memory.value()
        self.progress.setRange(0,0)
        self.signals=Signals()
        self.signals.done.connect(self.imported)
        self.signals.error.connect(self.failed)
        self.signals.progress.connect(lambda n:self.log.append(f"Read {n:,} rows"))
        def run():
            db=None
            try:
                db=connect(memory)
                n=import_rx(db,path,lambda count:self.signals.progress.emit(count),sheet_name=selected,memory_gb=memory)
                db.close()
                db=None
                self.signals.done.emit(n)
            except Exception:self.signals.error.emit(traceback.format_exc())
            finally:
                if db is not None:db.close()
        threading.Thread(target=run,daemon=True).start()
    def imported(self,n):
        self.progress.setRange(0,100);self.progress.setValue(100)
        self.log.append(f"Imported {n:,} rows.")
        self.db.close();self.db=connect(self.memory.value());self.reset_filters()
    def failed(self,msg):
        self.progress.setRange(0,100);self.progress.setValue(0);self.log.append(msg);self.error(msg)

if __name__=="__main__":
    app=QApplication(sys.argv);app.setStyleSheet(CSS)
    win=Window();win.show();sys.exit(app.exec())
