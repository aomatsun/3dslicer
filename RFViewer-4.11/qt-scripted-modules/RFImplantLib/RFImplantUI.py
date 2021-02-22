import qt
import logging

import ctk
import json
import slicer

from RFViewerHomeLib import createButton, translatable, Signal
from RFImplantLib import Roles

@translatable
class RFImplantUI(qt.QWidget):
  def __init__(self):
    qt.QWidget.__init__(self)

    self._filterModel = qt.QSortFilterProxyModel()
    self._filterModel.setFilterCaseSensitivity(qt.Qt.CaseInsensitive)
    self.implantLayout = qt.QVBoxLayout()
    self.implantLayout.setSpacing(10)

    filterLayout = qt.QHBoxLayout()
    filterLabel = qt.QLabel()
    filterLabel.text = self.tr("Filter:")
    filterLayout.addWidget(filterLabel)
    filterLayout.addWidget(self.createFilter())
    self._addedImplantListView = self.createAddedImplantListView()
    self._listView = self.createImplantListView()

    disablePlacementButton = createButton(self.tr("Disable current implant's placement"), self.disableImplantPlacement)

    self.implantLayout.addWidget(self._addedImplantListView)
    # self.implantLayout.addWidget(disablePlacementButton)
    self.implantLayout.addLayout(filterLayout)
    self.implantLayout.addWidget(self._listView)
    self.implantLayout.addWidget(createButton(self.tr("Load"), self.loadCurrentImplant))

    self.setLayout(self.implantLayout)
    self.loadImplantRequested = Signal("implantFilePath")
    self.selectCurrentImplantSignal = Signal("currentImplant")
    self.hideImplantSignal = Signal()
    self.showImplantSignal = Signal()
    self.deleteImplantSignal = Signal()
    self.disablePlacerSignal = Signal()

  def enforceMinimumSize(self):
    """ Overwrites the default height automatically set by Qt"""
    self._addedImplantListView.minimumHeight = 70
    self._listView.minimumHeight = 400

  def createFilter(self):
    """
    Create a layout with a button, a slider and a label which displays the slider value
    return a layout, the button, the slider and the label
    """

    filterLineEdit = qt.QLineEdit()
    def filterByWildcard():
      self._filterModel.setFilterWildcard(filterLineEdit.text)

    filterLineEdit.connect("textChanged(QString)", filterByWildcard)

    return filterLineEdit

  def createAddedImplantListView(self):
    """Create the view which listed the added implants"""
    self._addedImplantModel = qt.QStandardItemModel()
    listView = qt.QListView()
    listView.setModel(self._addedImplantModel)
    listView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    listView.setContextMenuPolicy(qt.Qt.ActionsContextMenu)
    listView.connect("clicked(QModelIndex)", self.selectCurrentImplant)

    hideAction = qt.QAction(self.tr("Hide"), listView)
    hideAction.triggered.connect(self.hideImplant)
    listView.addAction(hideAction)

    showAction = qt.QAction(self.tr("Show"), listView)
    showAction.triggered.connect(self.showImplant)
    listView.addAction(showAction)

    deleteAction = qt.QAction(self.tr("Delete"), listView)
    deleteAction.triggered.connect(self.deleteImplant)
    listView.addAction(deleteAction)

    return listView

  def createImplantListView(self):
    """ Create the view where all non filtered implants will be listed"""
    listView = qt.QTreeView()
    listView.name = 'll'
    # listView.setViewMode(qt.QListView.ListMode)
    # listView.setUniformItemSizes(True)
    # listView.setWrapping(True)
    # listView.setMovement(qt.QListView.Static)
    # listView.setFlow(qt.QListView.TopToBottom)
    # listView.setResizeMode(qt.QListView.Adjust)  # resize list view if widget width is changed
    # listView.setSpacing(0)
    listView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)

    listView.setModel(self._filterModel)
    listView.connect("doubleClicked(QModelIndex)", self.loadCurrentImplant)

    return listView

  def setModel(self, implantModel):
    """ Initialize the list view with a model that contains elements filling all Roles"""
    self._filterModel.setSourceModel(implantModel)
    self._implantModel = implantModel

  def setAddedImplantModel(self, addedImplantModel):
    """Initialize the list view with added implants model """
    self._addedImplantModel.setSourceModel(addedImplantModel)

  def loadCurrentImplant(self):
    """ Triggered when double-click on implant or on "Load" button click """
    implantFilePath = self._filterModel.data(self._listView.currentIndex(), Roles.file)
    self.loadImplantRequested.emit(implantFilePath)

    item = qt.QStandardItem()
    item.setText(slicer.mrmlScene.GetUniqueNameByString('Implant '))
    self._addedImplantModel.appendRow(item)

  def disableImplantPlacement(self):
    self.disablePlacerSignal.emit()

  def selectCurrentImplant(self):
    self.selectCurrentImplantSignal.emit(self._addedImplantListView.currentIndex().row())

  def hideImplant(self):
    self.selectCurrentImplant()
    self.hideImplantSignal.emit()

  def showImplant(self):
    self.selectCurrentImplant()
    self.showImplantSignal.emit()

  def deleteImplant(self):
    self.selectCurrentImplant()
    self.deleteImplantSignal.emit()
    self._addedImplantModel.removeRow(self._addedImplantListView.currentIndex().row())

  def getParameterDict(self):
    stringList = []
    for i in range(self._addedImplantModel.rowCount()):
      item = self._addedImplantModel.item(i)
      stringList.append(item.text())
    return json.dumps({"listViewItem": stringList})

  def loadFromParameterDict(self, paramDict):
    self._addedImplantModel.clear()
    try:
      dictionary = json.loads(paramDict)
      stringList = dictionary["listViewItem"]
      for string in stringList:
        item = qt.QStandardItem()
        item.setText(string)
        self._addedImplantModel.appendRow(item)
    except ValueError:
      pass