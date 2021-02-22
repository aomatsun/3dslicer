import json
import logging
import os

import ctk
import numpy as np
import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from shutil import copyfile

from RFImplantLib import RFImplantUI, Roles, RFImplantObject
from RFViewerHomeLib import createButton, createFileSelector, translatable, RFViewerWidget, nodeID, getNodeByID, \
    removeNodeFromMRMLScene, wrapInQTimer, TemporarySymlink, getShortPathToExistingPath
from RFVisualizationLib import showInMainViews
from collections import deque
class RFImplant(ScriptedLoadableModule):
    """
    Module responsible for wrapping calls to volume Implant implemented as a Command Line Interface module
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)

        self.parent.title = "RF Implant"
        self.parent.categories = ["RFCo"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


@translatable
class RFImplantWidget(RFViewerWidget):
    def __init__(self, parent):
        RFViewerWidget.__init__(self, parent)
        self._implantUI = RFImplantUI()
        self._dbLineEdit = None
        self._dbFilePath = None
        self._implantDataSubDir = 'ImplantVMZ'
        self._sceneImplants = []
        self._currentImplant = None
        self._volume = None
        self._tmpSymlink = TemporarySymlink()

    def setVolumeNode(self, volumeNode):
        self._volume = volumeNode

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        self.layout.addWidget(self._implantUI)
        self._implantUI.loadImplantRequested.connect(self.loadImplant)
        self._implantUI.selectCurrentImplantSignal.connect(self.currentImplantChanged)
        self._implantUI.hideImplantSignal.connect(self.hideCurrentImplant)
        self._implantUI.showImplantSignal.connect(self.showCurrentImplant)
        self._implantUI.deleteImplantSignal.connect(self.deleteCurrentImplant)
        self._implantUI.disablePlacerSignal.connect(self.disableImplantPlacer)

        advancedSection = self.addAdvancedSection()
        advancedLayout= qt.QFormLayout(advancedSection)
        self._dbLineEdit = createFileSelector(self.currentPathChanged,
                                              [self.tr("Microsoft Access DB (*.accdb *.mdb)")])
        advancedLayout.addRow(self.tr("DB"), self._dbLineEdit)

        self.layout.addStretch()

        self.openDB()

    def enter(self):
        """Called each time the Implant panel is set current"""
        self._implantUI.enforceMinimumSize()

    def currentPathChanged(self):
        self.openDB()

    @wrapInQTimer
    def openDB(self):
        implants, companies, productLines = self.readImplants(self._dbLineEdit.currentPath)
        if implants is None:
            return
        rootDir = os.path.dirname(self._dbLineEdit.currentPath)
        self._tmpSymlink.setTargetDir(rootDir)
        # model = self.createImplantModel(implants, rootDir)
        model = self.createImplantModel(companies, productLines, implants, self._tmpSymlink.getSymlinkPath())
        self._implantUI.setModel(model)
        self._dbLineEdit.addCurrentPathToHistory()

    def readImplants(self, dbFilePath):
        """Read Microsoft Access database and extract all implants, companies and product lines"""
        dbFilePath = os.path.normpath(dbFilePath)
        if dbFilePath == self._dbFilePath:
            return None, None, None

        db = qt.QSqlDatabase.addDatabase("QODBC")
        db.setDatabaseName(f'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};FIL={{MS Access}};DBQ={dbFilePath}')
        if not db.open():
            logging.error(f'Failed to open {dbFilePath} : {db.lastError()}')
            return None, None, None

        self._dbFilePath = dbFilePath
        companies = {}
        companyQuery = qt.QSqlQuery("SELECT * FROM Company", db)
        while companyQuery.next():
            companyId = companyQuery.value(0)
            companyName = companyQuery.value(1)
            favorite = companyQuery.value(2)
            companies[companyId] = {
                'companyName': companyName,
                'favorite': favorite
            }

        productLines = {}
        productLineQuery = qt.QSqlQuery(db)
        productLineQuery.setForwardOnly(True)
        productLineQuery.exec("SELECT * FROM ProductLine")
        while productLineQuery.next():
            productId = productLineQuery.value(0)
            companyId = productLineQuery.value(1)
            model = productLineQuery.value(2)
            favorite = productLineQuery.value(3)
            productLines[productId] = {
                'companyId': companyId,
                'model': model,
                'favorite': favorite
            }

        implants = {}
        implantQuery = qt.QSqlQuery(db)
        implantQuery.setForwardOnly(True)
        implantQuery.exec("SELECT * FROM ImplantTree")
        while implantQuery.next():
            implantId =  implantQuery.value(0)
            productId = implantQuery.value(1)
            implant = {
                'productId': productId,
                'articleNumber': implantQuery.value(2),
                'diameter1': implantQuery.value(3),
                'diameter2': implantQuery.value(4),
                'length': implantQuery.value(5),
                'total_length': implantQuery.value(6),
                'insertion_depth': implantQuery.value(7),
                'color': implantQuery.value(8),
                'abutment': implantQuery.value(9),
                'viewCheck': implantQuery.value(10),
                'favorite': implantQuery.value(11),
                'file_name': implantQuery.value(12),
                'image_file_name': implantQuery.value(13),
                'axis': implantQuery.value(14)
            }
            product = productLines.get(productId, {})
            companyId = product.get('companyId')
            implant.update({
                'companyId': companyId,
                'companyName': companies.get(companyId).get('companyName'),
                'model': product.get('model')
            })
            implants[implantId] = implant

        return implants, companies, productLines

    # def createImplantModel(self, implants, rootDir):
    #     model = qt.QStandardItemModel()
    #     root = model.invisibleRootItem()
    #     for implantId, implant in implants.items():
    #         item = qt.QStandardItem()
    #         iconFilePath = os.path.join(rootDir, self._implantDataSubDir, implant['image_file_name'])
    #         pixmap = qt.QPixmap(iconFilePath)
    #         item.setIcon(qt.QIcon(pixmap))
    #         item.setSizeHint(qt.QSize(60, 60))
    #         item.setText('{} {}\n{} {}'.format(
    #             implant['companyName'],
    #             implant['model'],
    #             implant['diameter1'],
    #             implant['length']))
    #         item.setToolTip(iconFilePath)
    #         item.setData(implantId, Roles.id)
    #         item.setData(implant['companyName'], Roles.company)
    #         item.setData(implant['model'], Roles.model)
    #         item.setData(implant['diameter1'], Roles.diameter)
    #         item.setData(implant['length'], Roles.length)
    #         implantFilePath = os.path.join(rootDir, self._implantDataSubDir, implant['file_name'])
    #         item.setData(implantFilePath, Roles.file)
    #         root.appendRow(item)

    #     return model
    def createImplantModel(self, companies, productLines, implants, rootDir):
        
        model = qt.QStandardItemModel()
        root = model.invisibleRootItem()
        for companyId, company in companies.items():
            companyItem = qt.QStandardItem(company['companyName'])
            for productId, product in productLines.items():
                if companyId != product['companyId']:
                    continue
                productItem = qt.QStandardItem(product['model'])
                for implantId, implant in implants.items():
                    if productId != implant['productId']:
                        continue
                    item = qt.QStandardItem()
                    iconFilePath = os.path.join(rootDir, self._implantDataSubDir, implant['image_file_name'])
                    pixmap = qt.QPixmap(iconFilePath)
                    item.setIcon(qt.QIcon(pixmap))
                    item.setSizeHint(qt.QSize(60, 60))
                    item.setText('{} - {} {} {}'.format(
                        implant['companyName'],
                        implant['model'],
                        implant['diameter1'],
                        implant['length']))
                    item.setToolTip(iconFilePath)
                    item.setData(implantId, Roles.id)
                    item.setData(implant['companyName'], Roles.company)
                    item.setData(implant['model'], Roles.model)
                    item.setData(implant['diameter1'], Roles.diameter)
                    item.setData(implant['length'], Roles.length)
                    implantFilePath = os.path.join(rootDir, self._implantDataSubDir, implant['file_name'])
                    item.setData(implantFilePath, Roles.file)
                    productItem.appendRow(item)
                companyItem.appendRow(productItem)
            root.appendRow(companyItem)
      
        return model

    def loadImplant(self, implantFilePath):
        newImplant = RFImplantObject.loadFromFilePath(getShortPathToExistingPath(implantFilePath))
        self._centerImplantNearFace(newImplant)
        self._sceneImplants.append(newImplant)
        self.changeCurrentImplant(newImplant)

    def _centerImplantNearFace(self, newImplant):
        """Positions new implant near face of the patient"""
        if self._volume is None:
            return

        # Calculate center of Volume bounds
        vol_bounds = [0] * 6
        self._volume.GetRASBounds(vol_bounds)
        implant_position = [np.mean(vol_bounds[0:2]), np.mean(vol_bounds[2:4]), np.mean(vol_bounds[4:6])]

        # Move Y direction halfway towards front of the face
        implant_position[1] = np.mean([implant_position[1], vol_bounds[3]])

        # Apply shift to the markups position
        newImplant.markupsNode.SetNthControlPointPosition(0, *implant_position)

    def currentImplantChanged(self, implantID):
        """
        Update the current implane
            implantID: Id of the implant in the list view (0 means that it's the first element of the list view)
        """
        self.changeCurrentImplant(self._sceneImplants[implantID])

    def changeCurrentImplant(self, implant):
        self.enablePlacementOnImplant(False, self._currentImplant)
        self._currentImplant = implant
        self.enablePlacementOnImplant(True, self._currentImplant)

    def getCurrentImplantSceneIndex(self):
        """
        Return the current implant id from the scene implants list
        None returned value means that the current implant is not in the scene implants list
        """
        for i, implant in enumerate(self._sceneImplants):
            if implant == self._currentImplant:
                return i
        return None


    def deleteCurrentImplant(self):
        """
        Delete implant and markups
            implant: tuple which contains the implant model node and the placement markups node
        """
        index = self.getCurrentImplantSceneIndex()
        if index is None:
            return

        del self._sceneImplants[index]
        self._currentImplant = None

    def disableImplantPlacer(self):
        """
        Disable the placer widget on the current selected implant
        """
        self.enablePlacementOnImplant(False, self._currentImplant)

    def hideCurrentImplant(self):
        self.setCurrentImplantVisibility(False)

    def showCurrentImplant(self):
        self.setCurrentImplantVisibility(True)

    def setCurrentImplantVisibility(self, visibility):
        """
        Show or hide current implant
            visibility: boolean which define is implant is visibled (True) or hidden (False)
        """
        if self._currentImplant is not None:
            self._currentImplant.setDisplayVisibility(visibility)

    def enablePlacementOnImplant(self, enable, implant):
        if implant is None:
            return
        implant.enablePlacement(enable)


    def onSessionAboutToBeSaved(self):
        """Override from RFViewerWidget"""
        self.saveState()

    def onSessionLoaded(self):
        """Override from RFViewerWidget"""
        self.applyState()

    def saveState(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        implantIds = [(implant.getParameterDict()) for implant in self._sceneImplants]
        parameter.SetParameter("Implants", json.dumps(implantIds))
        parameter.SetParameter("ImplantsUI", self._implantUI.getParameterDict())

    def applyState(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        self._implantUI.loadFromParameterDict(parameter.GetParameter("ImplantsUI"))
        implantIds = json.loads(parameter.GetParameter("Implants"))

        for param in implantIds:
            implant = RFImplantObject.loadFromParameterDict(param)
            self._sceneImplants.append(implant)
            self.enablePlacementOnImplant(False, implant)
        self._volume = self._dataLoaderWidget.getCurrentVolumeNode()
    def clean(self):
        """Override from RFViewerWidget"""
        self._currentImplant = None
        self._sceneImplants.clear()