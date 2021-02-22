import os
import ctk
import qt
import slicer
import ScreenCapture
from RFViewerHomeLib import translatable, warningMessageBox, informationMessageBox, Icons, TemporarySymlink, \
    ExportDirectorySettings
from enum import IntEnum, unique
import vtk
from RFExport import RFExportWidget
@translatable
class RFSessionSerialization(object):
    """Class responsible for saving and restoring viewer session"""

    def __init__(self, rfWidgets, loadWidget):
        self._rfWidgets = rfWidgets
        self._loadWidget = loadWidget
        self._sessionFileFilter = self.tr("Session File") + " (*.mrb)"
        self._sessionFileName = "RFViewerSession.mrb"
        self._tmpSymlink = TemporarySymlink()

    def onSaveSession(self):
        if not self.isSessionSavingPossible():
            warningMessageBox(self.tr("Save session impossible"), self.tr(
                "Session saving is not possible until a volume is first loaded in the scene"))
            return

        savePath = self._querySessionSavePath()
        if savePath:
            self.saveSession(savePath)

    def onLoadSession(self):
        loadPath = self._querySessionLoadPath()
        if loadPath:
            self.loadSession(loadPath)

    def _lastSessionPath(self):
        return os.path.join(ExportDirectorySettings.load(), self._sessionFileName)

    def _querySessionSavePath(self):
        return qt.QFileDialog.getSaveFileName(None, self.tr("Save session file"), self._lastSessionPath(),
                                              self._sessionFileFilter)

    def _querySessionLoadPath(self):
        return qt.QFileDialog.getOpenFileName(None, self.tr("Load session file"), self._lastSessionPath(),
                                              self._sessionFileFilter)

    def saveSession(self, sessionFilePath, showMessageBox=True):
        # Notify session about to be saved
        pixmap = qt.QPixmap(":/Icons/Cursor.png")
        cursor = qt.QCursor(pixmap, 32, 32)
        qt.QApplication.setOverrideCursor(cursor)
        
        for widget in self._rfWidgets:
            widget.onSessionAboutToBeSaved()

        # Save scene to path
        slicer.util.saveScene(self._tmpSymlink.getSymlinkToNewPath(sessionFilePath))

        
        qt.QApplication.restoreOverrideCursor()

        if showMessageBox:
            warningMessageBox(self.tr("Session saved"), self.tr("Session was successfully saved."))

        # Save session directory to settings
        ExportDirectorySettings.save(sessionFilePath)
        path = os.path.join(ExportDirectorySettings.load(), "Session-screenshot.png")
        # msg = qt.QMessageBox()
        # msg.setText(path)
        # msg.exec_()
        # cap = ScreenCapture.ScreenCaptureLogic()
        # cap.showViewControllers(False)
        # cap._captureImageFromView(path)
        # cap.showViewControllers(True)
        slicer.app.processEvents()
        slicer.util.forceRenderAllViews()

        # Grab the main window and use only the viewport's area
        allViews = slicer.app.layoutManager().viewport()
        topLeft = allViews.mapTo(slicer.util.mainWindow(), allViews.rect.topLeft())
        bottomRight = allViews.mapTo(slicer.util.mainWindow(), allViews.rect.bottomRight())
        imageSize = bottomRight - topLeft

        if imageSize.x() < 2 or imageSize.y() < 2:
            # image is too small, most likely it is invalid
            raise ValueError('Capture image from view failed')

        img = ctk.ctkWidgetsUtils.grabWidget(slicer.util.mainWindow(),
                                            qt.QRect(topLeft.x(), topLeft.y(), imageSize.x(), imageSize.y()))

        img.save(path)
    def loadSession(self, sessionFilePath):
        # Deactivate load widget notifications
        self._loadWidget.setNewVolumeSettingEnabled(False)

        # Notify session about to be loaded
        for widget in self._rfWidgets:
            widget.clean()

        # Clear scene
        slicer.mrmlScene.Clear()

        # Load scene from session path
        if os.path.exists(self._tmpSymlink.getSymlinkToExistingPath(sessionFilePath)):
            slicer.util.loadScene(self._tmpSymlink.getSymlinkToExistingPath(sessionFilePath))
        else:
            slicer.util.loadScene(sessionFilePath)
        # Notify scene was loaded
        for widget in self._rfWidgets:
            widget.onSessionLoaded()
        slicer.app.processEvents()
        slicer.util.forceRenderAllViews()
        # Reactivate load widget notifications
        self._loadWidget.setNewVolumeSettingEnabled(True)

        # Save session directory to settings
        ExportDirectorySettings.save(sessionFilePath)

    def isSessionSavingPossible(self):
        return self._loadWidget.getCurrentNodeID() != ""
