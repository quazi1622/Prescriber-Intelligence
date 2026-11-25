"""Prescriber Intelligence: portable PySide6 desktop dashboard."""
import sys,threading,traceback
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QFileDialog,QMessageBox,QTextEdit,QProgressBar,QHeaderView,QCompleter)
from core import connect,import_rx,import_audit,has_rankings,ranking,choices,write_csv,generate_drafts,available_sheets,DB,DATA
from routing import import_hierarchy
from product_analysis import product_choices,filtered_rankings,has_product_index,generic_rx_shares,competitor_brand_shares,prescriber_share_rankings,generic_scope_summary,regional_competitor_shares

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

class SearchableCombo(QComboBox):
    """Editable dropdown with substring search and an explicit search button.

    Filtering is client-side against the already loaded options. User typing
    never becomes an SQL filter until a listed option is actually selected.
    """
    selectionCommitted=Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumWidth(145)
        self._selected_value=""
        completer=QCompleter(self.model(),self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)
        self.activated.connect(self._accept_selection)
        completer.activated[str].connect(self._completion_selected)
        self.lineEdit().setPlaceholderText("Type to search…")
        self.setToolTip("Type any part of an option, select a suggestion, or open the dropdown.")

    def _completion_selected(self, value):
        index=self.findText(value,Qt.MatchFixedString)
        if index>=0:
            self.setCurrentIndex(index)
            self._accept_selection()

    def _accept_selection(self, *args):
        index=self.findText(self.currentText(),Qt.MatchFixedString)
        if index<0:
            # Invalid partial text is not applied to analytics.
            prior=self.findText(self._selected_value,Qt.MatchFixedString)
            if prior>=0:self.setCurrentIndex(prior)
            return
        value=self.itemText(index)
        self._selected_value=value
        self.selectionCommitted.emit()

    def committed_text(self):
        return self._selected_value

    def commit_programmatic_selection(self):
        self._selected_value=self.currentText()

    def search_options(self):
        typed=self.lineEdit().text().strip()
        if typed==self._selected_value:
            # Search button on an existing selection opens all alternatives.
            self.lineEdit().clear()
            typed=""
        self.lineEdit().setFocus()
        completer=self.completer()
        completer.setCompletionPrefix(typed)
        completer.complete()

    def search_button(self):
        button=QPushButton("⌕")
        button.setFixedWidth(38)
        button.setToolTip("Search available options (case-insensitive, partial name)")
        button.clicked.connect(self.search_options)
        return button


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
        self.division=SearchableCombo();self.division.addItems(["ACD","CCD"])
        self.division.commit_programmatic_selection()
        self.region=SearchableCombo();self.ase=SearchableCombo();self.territory=SearchableCombo()
        self.top=QSpinBox();self.top.setRange(1,20);self.top.setValue(10)
        for label,widget in [("DIVISION",self.division),("RSE / REGION",self.region),("ASE",self.ase),("TERRITORY",self.territory),("TOP N",self.top)]:
            column=QVBoxLayout()
            column.addWidget(QLabel(label))
            if isinstance(widget,SearchableCombo):
                controls=QHBoxLayout()
                controls.setSpacing(3)
                controls.addWidget(widget)
                controls.addWidget(widget.search_button())
                column.addLayout(controls)
            else:
                column.addWidget(widget)
            filters.addLayout(column)
        a.addLayout(filters)
        product_filters=QHBoxLayout()
        self.generic=SearchableCombo();self.brand=SearchableCombo()
        for name,widget in [("GENERIC",self.generic),("BRAND",self.brand)]:
            group=QVBoxLayout()
            group.addWidget(QLabel(name))
            controls=QHBoxLayout()
            controls.setSpacing(3)
            controls.addWidget(widget)
            controls.addWidget(widget.search_button())
            group.addLayout(controls)
            product_filters.addLayout(group)
        a.addLayout(product_filters)
        self.metrics=[]
        stats=QHBoxLayout()
        for _ in range(3):
            label=QLabel("—");label.setObjectName("metric");stats.addWidget(label);self.metrics.append(label)
        a.addLayout(stats)
        share_stats=QHBoxLayout()
        self.share_metrics=[]
        for _ in range(3):
            label=QLabel("Select a Generic to compare shares")
            label.setObjectName("metric")
            share_stats.addWidget(label)
            self.share_metrics.append(label)
        a.addLayout(share_stats)
        self.competitors=QTableWidget()
        self.competitors.setColumnCount(5)
        self.competitors.setHorizontalHeaderLabels(
            ["RSE / Region","Competitor brand","Observed Rx","Region generic Rx","Regional Rx share"])
        self.competitors.setMaximumHeight(190)
        self.competitors.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        a.addWidget(QLabel("COMPETITOR BRAND SHARE — RSE REGIONAL LEVEL (INDEPENDENT OF ASE / MPE)"))
        a.addWidget(self.competitors)
        actions=QHBoxLayout()
        refresh=QPushButton("↻  REFRESH");refresh.clicked.connect(self.refresh);actions.addWidget(refresh)
        export=QPushButton("↓  EXPORT CSV");export.clicked.connect(self.export);actions.addWidget(export)
        actions.addStretch();a.addLayout(actions)
        self.table=QTableWidget();self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels(["RSE","ASE","Territory","#","Doctor Code","Prescriber","Specialty","Generic Rx","Azithrocin Rx","Competitor Rx","Generic Rx Share","Azithrocin Rx Share","Competitor Rx Share"])
        self.table.setAlternatingRowColors(True);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(5,245);self.table.setColumnWidth(6,150);a.addWidget(self.table)
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
        self.division.selectionCommitted.connect(self.reset_filters)
        self.region.selectionCommitted.connect(self.update_ase)
        self.ase.selectionCommitted.connect(self.update_territory)
        self.territory.selectionCommitted.connect(self.reset_products)
        self.generic.selectionCommitted.connect(self.update_brand)
        self.brand.selectionCommitted.connect(self.refresh)
        self.top.valueChanged.connect(self.refresh)
        self.reset_filters();self.load_audit()
    def selected(self,c):
        value=c.committed_text() if isinstance(c,SearchableCombo) else c.currentText()
        return "" if value in ("All","") else value
    def fill(self,c,values):
        c.blockSignals(True);old=c.currentText();c.clear();c.addItem("All");c.addItems(values)
        if old in values:c.setCurrentText(old)
        if isinstance(c,SearchableCombo):c.commit_programmatic_selection()
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
            brands=product_choices(self.db,self.division.currentText(),
                "brand",self.selected(self.region),self.selected(self.ase),self.selected(self.territory),
                generic=self.selected(self.generic))
            self.fill(self.brand,brands)
            if (self.selected(self.generic).casefold()=="azithromycin"
                    and not self.selected(self.brand)):
                match=next((b for b in brands if b.casefold()=="azithrocin"),None)
                if match:
                    self.brand.setCurrentText(match)
                    self.brand.commit_programmatic_selection()
            self.refresh()
        except Exception as e:self.error(str(e))
    def refresh(self,*args):
        try:
            division=self.division.committed_text()
            region=self.selected(self.region)
            ase=self.selected(self.ase)
            territory=self.selected(self.territory)
            generic=self.selected(self.generic)
            brand=self.selected(self.brand)
            if generic and has_product_index(self.db):
                self.rows=prescriber_share_rankings(
                    self.db,division,self.top.value(),region,ase,territory,generic,brand)
            else:
                self.rows=[]
            self.table.setRowCount(len(self.rows))
            for i,record in enumerate(self.rows):
                for j,value in enumerate(record):
                    if j>=10:
                        display="—" if value is None else f"{value:.1f}%"
                    else:
                        display=str(value if value is not None else "")
                    self.table.setItem(i,j,QTableWidgetItem(display))
            self.metrics[0].setText(f"{len(self.rows):,}   RANKED PRESCRIBERS")
            self.metrics[1].setText(
                f"{len({(r[0],r[1],r[2]) for r in self.rows}):,}   TERRITORIES")
            self.metrics[2].setText(
                f"{sum(int(r[7]) for r in self.rows):,}   GENERIC Rx (RANKED)")
            if generic:
                share=generic_scope_summary(
                    self.db,division,generic,region,ase,territory,brand)
                def form(value):
                    return "—" if value is None else f"{value:.1f}%"
                self.share_metrics[0].setText(
                    form(share["generic_share"])+"   GENERIC Rx SHARE")
                self.share_metrics[1].setText(
                    form(share["brand_share"])+"   "+(brand or "SELECT BRAND")+" Rx SHARE")
                self.share_metrics[2].setText(
                    form(share["competitor_share"])+"   COMPETITOR Rx SHARE")
                # RSE is the only geography used in this query.
                regional=regional_competitor_shares(
                    self.db,division,generic,region)
                self.competitors.setRowCount(len(regional))
                for i,record in enumerate(regional):
                    for j,value in enumerate(record):
                        display=f"{value:.1f}%" if j==4 else str(value)
                        self.competitors.setItem(i,j,QTableWidgetItem(display))
            else:
                for label in self.share_metrics:
                    label.setText("Select a Generic to compute Rx shares")
                self.competitors.setRowCount(0)
        except Exception as e:
            self.error(str(e))
    def error(self,message):
        QMessageBox.critical(self,"Prescriber Intelligence",message)
    def export(self):
        if not self.rows:return self.error("Import the prescription workbook first.")
        path,_=QFileDialog.getSaveFileName(self,"Export ranking",str(DATA/"top_prescribers.csv"),"CSV (*.csv)")
        if path:
            import csv
            with open(path,"w",newline="",encoding="utf-8-sig") as handle:
                writer=csv.writer(handle)
                writer.writerow(["RSE","ASE","Territory","Rank","Doctor Code","Prescriber",
                    "Specialty","Generic Rx","Selected Brand Rx","Competitor Rx",
                    "Generic Rx Share (%)","Selected Brand Rx Share (%)",
                    "Competitor Rx Share (%)"])
                writer.writerows(self.rows)
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
