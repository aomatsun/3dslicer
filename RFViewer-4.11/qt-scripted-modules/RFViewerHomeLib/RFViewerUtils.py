import _winapi
import ctypes
import os
from ctypes import wintypes
from enum import Enum
from itertools import count

import ctk
import qt
import slicer
import vtk


def translatable(cls):
    """Decorator to add translation support to the decorated class.

    Decorator needs to be used for both Qt widgets and other widgets to allow translation to work properly
    """

    def tr(self, name):
        return qt.QCoreApplication.translate(self.__class__.__name__, name)

    setattr(cls, 'tr', tr)
    return cls


class ProgressBar(qt.QWidget):
    """Simple Widget holding a name and a progress bar"""

    def __init__(self, taskName):
        qt.QWidget.__init__(self)
        layout = qt.QHBoxLayout(self)

        self._taskName = qt.QLabel(taskName)
        layout.addWidget(self._taskName)

        self._progressBar = qt.QProgressBar()
        layout.addWidget(self._progressBar)

        self.setInfinite()

    def setInfinite(self):
        self.setRange(0, 0)

    def setRange(self, minRange, maxRange):
        self._progressBar.setRange(minRange, maxRange)

    def setValue(self, value):
        self._progressBar.setValue(value)

    def setTaskName(self, taskName):
        self._taskName.setText(taskName)


class Icons(object):
    """ Object responsible for the different icons in the module. The module doesn't have any icons internally but pulls
    icons from slicer and the other modules.
    """

    toggleVisibility = qt.QIcon(":/Icons/VisibleOrInvisible.png")
    visibleOn = qt.QIcon(":/Icons/VisibleOn.png")
    visibleOff = qt.QIcon(":/Icons/VisibleOff.png")
    editSegmentation = qt.QIcon(":/Icons/Paint.png")
    editPoint = qt.QIcon(":/Icons/Paint.png")
    delete = qt.QIcon(":/Icons/SnapshotDelete.png")
    cut3d = qt.QIcon(":/Icons/Medium/SlicerEditCut.png")
    loadDICOM = qt.QIcon(":Icons/Small/SlicerLoadDICOM.png")
    loadData = qt.QIcon(":Icons/Small/SlicerLoadData.png")


    sessionSave = qt.QIcon(":/Icons/sessionSave.png")
    exportDICOM = qt.QIcon(":/Icons/exportDICOM.png")
    reconstruction3d = qt.QIcon(":/Icons/reconstruction3d.png")
    measureTool = qt.QIcon(":/Icons/measureTool.png")
    implantTool = qt.QIcon(":/Icons/implantTool.png")
    PanoramaDisplay = qt.QIcon(":/Icons/PanoramaDisplay.png")
    PanoramaReconstruction = qt.QIcon(":/Icons/PanoramaReconstruction.png")
    segmentationTool = qt.QIcon(":/Icons/segmentationTool.png")
    Reset = qt.QIcon(":/Icons/undo.png")
    takeScreenshot = qt.QIcon(":/Icons/ViewCapture.png")
    AnnotationLine = qt.QIcon(":/Icons/AnnotationLine.png")
    Segmentation = qt.QIcon(":/Icons/GGO.png")
    AnnotationAngle = qt.QIcon(":/Icons/AnnotationAngle.png")
    Cursor = qt.QIcon(":/Icons/Cursor.png")
    DVDexport = qt.QIcon(":/Icons/DVDexport.png")
class WidgetUtils(object):
    """Helper class to extract widgets linked to an existing widget representation
    """

    @staticmethod
    def getChildrenContainingName(widget, childString):
        if not hasattr(widget, "children"):
            return []
        else:
            return [child for child in widget.children() if childString.lower() in child.name.lower()]

    @staticmethod
    def getFirstChildContainingName(widget, childString):
        children = WidgetUtils.getChildrenContainingName(widget, childString)
        return children[0] if children else None

    @staticmethod
    def getChildrenOfType(widget, childType):
        if not hasattr(widget, "children"):
            return []
        else:
            return [child for child in widget.children() if isinstance(child, childType)]

    @staticmethod
    def getFirstChildOfType(widget, childType):
        children = WidgetUtils.getChildrenOfType(widget, childType)
        return children[0] if children else None

    @staticmethod
    def hideChildrenContainingName(widget, childString):
        hiddenChildren = WidgetUtils.getChildrenContainingName(widget, childString)
        for child in WidgetUtils.getChildrenContainingName(widget, childString):
            child.visible = False
        return hiddenChildren

    @staticmethod
    def hideFirstChildContainingName(widget, childString):
        hiddenChild = WidgetUtils.getFirstChildContainingName(widget, childString)
        if hiddenChild:
            hiddenChild.visible = False
        return hiddenChild


def jumpSlicesToLocation(location, centerToLocation=True, sliceIds=None):
    """Helper function to position all the different slices to input location.

    Parameters
    ----------
    location: List[float] with x, y, z components
    centerToLocation: Bool
      If False, then the camera is centered to slicer instead of location
    sliceIds: List[Str] (optional)
      List of slice Ids which should jump to location. If the list is empty or undefined, all the slices will jump to
      location.
    """
    sliceIds = sliceIds if sliceIds else []
    sliceNodes = slicer.util.getNodesByClass("vtkMRMLSliceNode")
    for sliceNode in sliceNodes:
        if sliceIds and not sliceNode.GetID() in sliceIds:
            continue

        if centerToLocation:
            sliceNode.JumpSliceByCentering(location[0], location[1], location[2])
        else:
            sliceNode.JumpSliceByOffsetting(location[0], location[1], location[2])


def jumpSlicesToNthMarkupPosition(markupNode, i_nthMarkup, centerToLocation=True):
    """Helper function to position all the different slices to the nth markup position in input node

    Parameters
    ----------
    markupNode: vtkMRMLMarkupsNode
      Fiducial node with at least i_nthMarkup + 1 nodes
    i_nthMarkup: int or None
      Index of the markup we want to center the slices on
    centerToLocation: Bool
      If False, then the camera is centered to slicer instead of location
    """
    try:
        # Early return if incorrect index
        maxPoints = markupNode.GetMaximumNumberOfControlPoints()
        if markupNode.IsA('vtkMRMLMarkupsCurveNode'):
            maxPoints = markupNode.GetCurvePointsWorld().GetNumberOfPoints()
        isMarkupIndexInRange = 0 <= i_nthMarkup < maxPoints
        if i_nthMarkup is None or not isMarkupIndexInRange:
            return

        # Get fiducial position and center slices to it
        pos = [0] * 3
        markupNode.GetNthControlPointPosition(i_nthMarkup, pos)
        jumpSlicesToLocation(pos, centerToLocation, markupNode.GetDisplayNode().GetViewNodeIDs())

    except AttributeError:
        return


def createInputNodeSelector(nodeType, toolTip, callBack=None):
    """Creates node selector with given input node type, tooltip and callback when currentNodeChanged signal is emitted

    Parameters
    ----------
    nodeType: vtkMRML type compatible with qMRMLNodeComboBox
      Node type which will be displayed in the combo box
    toolTip: str
      Input selector hover text
    callBack: (optional) function
      Function called when qMRMLNodeComboBox currentNodeChanged is triggered.
      Function must accept a vtkMRMLNode input parameter

    Returns
    -------
    inputSelector : qMRMLNodeComboBox
      configured input selector
    """
    inputSelector = slicer.qMRMLNodeComboBox()
    inputSelector.nodeTypes = [nodeType]
    inputSelector.selectNodeUponCreation = False
    inputSelector.addEnabled = False
    inputSelector.removeEnabled = False
    inputSelector.noneEnabled = False
    inputSelector.showHidden = False
    inputSelector.showChildNodeTypes = False
    inputSelector.setMRMLScene(slicer.mrmlScene)
    inputSelector.setToolTip(toolTip)
    if callBack is not None:
        inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", callBack)
    return inputSelector


def createSingleMarkupFiducial(toolTip, markupName, markupColor=qt.QColor("red")):
    """Creates node selector for vtkMarkupFiducial type containing only one point.

    Parameters
    ----------
    toolTip: str
      Input selector hover text
    markupName: str
      Default name for the created markups when new markup is selected
    markupColor: (option) QColor
      Default color for the newly created markups (default = red)

    Returns
    -------
    qSlicerSimpleMarkupsWidget
    """
    markupNodeSelector = slicer.qSlicerSimpleMarkupsWidget()
    markupNodeSelector.objectName = markupName + 'NodeSelector'
    markupNodeSelector.toolTip = toolTip
    markupNodeSelector.setNodeBaseName(markupName)
    markupNodeSelector.tableWidget().hide()
    markupNodeSelector.defaultNodeColor = markupColor
    markupNodeSelector.markupsSelectorComboBox().noneEnabled = False
    markupNodeSelector.markupsPlaceWidget().placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceSingleMarkup
    markupNodeSelector.setMRMLScene(slicer.mrmlScene)
    slicer.app.connect('mrmlSceneChanged(vtkMRMLScene*)', markupNodeSelector, 'setMRMLScene(vtkMRMLScene*)')
    return markupNodeSelector


def createMultipleMarkupFiducial(toolTip, markupName, markupColor=qt.QColor("red")):
    """Creates node selector for vtkMarkupFiducial type containing only multiple points.

    Parameters
    ----------
    toolTip: str
      Input selector hover text
    markupName: str
      Default name for the created markups when new markup is selected
    markupColor: (option) QColor
      Default color for the newly created markups (default = red)

    Returns
    -------
    qSlicerSimpleMarkupsWidget
    """
    markupNodeSelector = createSingleMarkupFiducial(toolTip=toolTip, markupName=markupName, markupColor=markupColor)
    markupNodeSelector.markupsPlaceWidget().placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceMultipleMarkups
    markupNodeSelector.markupsPlaceWidget().setPlaceModePersistency(True)
    return markupNodeSelector


def createButton(name, callback=None, isCheckable=False, icon=None, toolTip=""):
    """Helper function to create a button with a text, callback on click and checkable status

    Parameters
    ----------
    name: str
      Label of the button
    callback: Callable
      Called method when button is clicked
    isCheckable: bool
      If true, the button will be checkable
    icon: Optional[qt.QIcon]
      Icon to set for the button
    toolTip: str
      Tooltip displayed on button hover

    Returns
    -------
    QPushButton
    """
    button = qt.QPushButton(name)
    if callback is not None:
        button.connect("clicked(bool)", callback)
    if icon is not None:
        button.setIcon(icon)
    button.toolTip = toolTip
    button.setCheckable(isCheckable)
    button.setFixedSize(50, 50)
    button.setIconSize(qt.QSize(40,40))
    return button


def createFileSelector(callback=None, nameFilters=None):
    """Convenient function to widget that selects a file on disk.
    You can call `addCurrentPathToHistory()` on the returned ctkPathLineEdit
    to save the path. An autocompletion menu will list saved path next time
    the application is started.
    """
    lineEdit = ctk.ctkPathLineEdit()
    lineEdit.filters = ctk.ctkPathLineEdit.Files
    if callback is not None:
        lineEdit.connect("currentPathChanged(QString)", callback)
    if nameFilters is not None:
        lineEdit.nameFilters = nameFilters
        lineEdit.settingKey = nameFilters[0]
    return lineEdit


def addInCollapsibleLayout(childWidget, parentLayout, collapsibleText, isCollapsed=True):
    """Wraps input childWidget into a collapsible button attached to input parentLayout.
    collapsibleText is writen next to collapsible button. Initial collapsed status is customizable
    (collapsed by default)
    """
    parentLayout.addWidget(wrapInCollapsibleButton(childWidget, collapsibleText, isCollapsed))


def wrapInCollapsibleButton(childWidget, collapsibleText, isCollapsed=True):
    """Wraps input childWidget into a collapsible button.
    collapsibleText is writen next to collapsible button. Initial collapsed status is customizable
    (collapsed by default)

    :returns ctkCollapsibleButton
    """
    collapsibleButton = ctk.ctkCollapsibleButton()
    collapsibleButton.text = collapsibleText
    collapsibleButton.collapsed = isCollapsed
    collapsibleButtonLayout = qt.QVBoxLayout()
    collapsibleButtonLayout.addWidget(childWidget)
    collapsibleButton.setLayout(collapsibleButtonLayout)
    return collapsibleButton


class Signal(object):
    """ Qt like signal slot connections. Enables using the same semantics with Slicer as qt.Signal lead to application
    crash.
    (see : https://discourse.slicer.org/t/custom-signal-slots-with-pythonqt/3278/5)

    Signal usage example :
        Creation : self.mySignal = Signal("Information on sent data")
        Connection : self.mySignal.connect(lambda x,y,y : print())
        Emission :
            self.mySignal.emit(x, y, z)
            self.mySignal(x, y, z)
        Disconnect :
            sigId = self.mySignal.connect(...)
            self.mySignal.disconnect(sigId)
    """

    def __init__(self, *typeInfo):
        self._id = count(0, 1)
        self._connectDict = {}
        self._typeInfo = str(typeInfo)

    def emit(self, *args, **kwargs):
        # Copy connection dict before iterating since some connection may be disconnected during call
        for slot in self._connectDict.copy().values():
            slot(*args, **kwargs)

    def connect(self, slot):
        nextId = next(self._id)
        self._connectDict[nextId] = slot
        return nextId

    def disconnect(self, connectId):
        if connectId in self._connectDict:
            del self._connectDict[connectId]
            return True
        return False

    def __call__(self, *args, **kwargs):
        self.emit(*args, **kwargs)


def removeNodeFromMRMLScene(node):
    """
    Remove node from slicer scene
    :param node: str or vtkMRMLNode - node to remove from scene
    """
    if node is None:
        return

    if isinstance(node, str):
        nodes = slicer.mrmlScene.GetNodesByName(node)
        nodes.UnRegister(slicer.mrmlScene)
        for node in list(nodes):
            removeNodeFromMRMLScene(node)
    elif slicer.mrmlScene.IsNodePresent(node):
        slicer.mrmlScene.RemoveNode(node)


def removeNodesFromMRMLScene(nodesToRemove):
    """Removes the input nodes from the scene. Nodes will no longer be accessible from the mrmlScene or from the UI.

    Parameters
    ----------
    nodesToRemove: List[vtkMRMLNode] or vtkMRMLNode
      Objects to remove from the scene
    """
    for node in nodesToRemove:
        removeNodeFromMRMLScene(node)


def horizontalSlider(value=0, singleStep=0.1, pageStep=0.1, minimum=0, maximum=1, toolTip=""):
    """
    Create a slider with the given input parameters
    """
    slider = slicer.qMRMLSliderWidget()
    slider.setValue(value)
    slider.singleStep = singleStep
    slider.pageStep = pageStep
    slider.maximum = maximum
    slider.minimum = minimum
    slider.toolTip = toolTip
    return slider


def getViewBySingletonTag(tag, isComposite=False):
    """
    Finds and return the first view node with the given input singleton tag

    :param tag: str or Enum - Singleton tag of the view to get
    :param isComposite: If true will look for vtkMRMLCompositeSliceNode, else for vtkMRMLSliceNode
    :return: ViewNode with the given input tag if found else None
    """
    if isinstance(tag, Enum):
        tag = tag.value

    classType = 'vtkMRMLSlice{}Node'.format("Composite" if isComposite else "")

    for i in range(slicer.mrmlScene.GetNumberOfNodesByClass(classType)):
        viewNode = slicer.mrmlScene.GetNthNodeByClass(i, classType)
        if viewNode.GetSingletonTag() == tag:
            return viewNode
    return None


def wrapInQTimer(func):
    """For reference counting issues, VTK objects should not be arguments."""

    def inner(*args, **kwargs):
        for arg in list(args) + list(kwargs.values()):
            if isinstance(arg, vtk.vtkObject):
                raise ValueError('VTK arguments are not allowed in wrapInQTimer')
        qt.QTimer.singleShot(0, lambda: func(*args, **kwargs))

    return inner


@wrapInQTimer
def showVolumeOnSlices(volume_id, viewTags):
    """
    Shows the input volume on the given input view tags.

    :param volume: vtkMRMLVolumeNode to display on the given slice
    :param viewTags: str or Enum - Singleton tag of the view on which the volume should be displayed
    """

    for viewTag in viewTags:
        view = getViewBySingletonTag(viewTag, isComposite=True)
        if view is not None:
            view.SetBackgroundVolumeID(volume_id)
@wrapInQTimer
def showVolumeOnSlice(volume_id, viewTag):
    """
    Shows the input volume on the given input view tags.

    :param volume: vtkMRMLVolumeNode to display on the given slice
    :param viewTags: str or Enum - Singleton tag of the view on which the volume should be displayed
    """

    view = getViewBySingletonTag(viewTag, isComposite=True)
    if view is not None:
        view.SetBackgroundVolumeID(volume_id)
          
class WindowLevelUpdater(object):
    """
    Class responsible for synchronizing the window level of a target volume with a source volume node
    """

    def __init__(self, sourceVolume, targetVolume):
        self._sourceVolume = sourceVolume
        self._targetVolume = targetVolume

        sourceDisplayNode, _ = self.getSourceAndTargetDisplayNodes()
        if sourceDisplayNode is None:
            raise ValueError("Invalid input nodes")

        sourceDisplayNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.synchroniseDisplayWithVolume)
        self.synchroniseDisplayWithVolume()

    def getSourceAndTargetDisplayNodes(self):
        def volumeScalarNode(volume):
            if volume is None:
                return None
            return volume.GetScalarVolumeDisplayNode()

        return volumeScalarNode(self._sourceVolume), volumeScalarNode(self._targetVolume)

    def synchroniseDisplayWithVolume(self, *_):
        sourceDisplayNode, targetDisplayNode = self.getSourceAndTargetDisplayNodes()
        if None in [sourceDisplayNode, targetDisplayNode]:
            return

        targetDisplayNode.SetWindowLevel(sourceDisplayNode.GetWindow(), sourceDisplayNode.GetLevel())
        targetDisplayNode.SetAndObserveColorNodeID(sourceDisplayNode.GetColorNodeID())


def nodeID(node):
    """Returns NodeID or empty string if node is None"""
    return node.GetID() if node else ""


def getNodeByID(node_id):
    """Returns Node corresponding to input nodeId. If node id cannot be found in scene, returns None"""
    if not node_id:
        return None
    return slicer.mrmlScene.GetNodeByID(node_id)


def toggleCheckBox(checkBox, lastCheckedState):
    """
    Toggle the input checkbox at least once to go to lastCheckedState.
    If checkbox state is the same as lastCheckedState, the checkbox will be toggled twice
    """
    if checkBox.checked == lastCheckedState:
        checkBox.setChecked(not checkBox.checked)
    checkBox.setChecked(lastCheckedState)


def strToBool(value):
    """Convert input string to bool"""
    if isinstance(value, bool):
        return value
    elif isinstance(value, str):
        return value.lower() in ['true', 'yes', '1', 'y', 't']
    return False


def messageBox(title, message, messageType=qt.QMessageBox.Information):
    """Opens a message box while handling the stay on top flag when main window is always on Top"""
    dlg = qt.QMessageBox(messageType, title, message)
    # if strToBool(qt.QSettings().value("windowAlwaysOnTop")):
    #     dlg.setWindowFlag(qt.Qt.WindowStaysOnTopHint, True)
    dlg.setWindowFlag(qt.Qt.WindowStaysOnTopHint, True)
    dlg.exec()


def informationMessageBox(title, message):
    """Opens an information message box while handling the stay on top flag"""
    messageBox(title, message, qt.QMessageBox.Information)


def warningMessageBox(title, message):
    """Opens a warning message box while handling the stay on top flag"""
    messageBox(title, message, qt.QMessageBox.Warning)


def getShortPathToExistingPath(path):
    """
    Gets the win32 short path for input path. (function is only valid on windows)
    http://stackoverflow.com/a/23598461/200291

    :param path: str - Valid path to a directory or file
    :raises: ValueError if input path doesn't exist
    :return: Short path equivalent to input path containing no special characters
    """
    _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
    _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    _GetShortPathNameW.restype = wintypes.DWORD

    if not os.path.exists(path):
        raise ValueError(f"Path needs to exists before its short path is queried {path}")

    output_buf_size = len(path)
    while True:
        output_buf = ctypes.create_unicode_buffer(output_buf_size)
        needed = _GetShortPathNameW(path, output_buf, output_buf_size)
        if output_buf_size >= needed:
            return output_buf.value
        else:
            output_buf_size = needed


@translatable
class TemporarySymlink(object):
    """
    Object responsible for creating a symlink path to a target directory. The symlink will be stored in a temporary
    directory and will be cleaned up when the object is deleted or when the Slicer application closes.
    This object is used to avoid read and write errors when accessing paths with special chars.
    """

    class SystemSemaphore(qt.QRunnable):
        """Thread runnable system semaphore for the symlink directory resources"""

        def __init__(self):
            qt.QRunnable.__init__(self)
            self._semaphore = qt.QSystemSemaphore("RFViewerTemporarySymlink", 1)
            self.semaphoreAcquired = False

        def run(self):
            # Call to semaphore acquire is blocking until semaphore is released by other instances
            self._semaphore.acquire()
            self.semaphoreAcquired = True

    _symlinkDirInitializationDone = False
    _symlinkBaseName = "symLink"
    _tmpSymlinkSemaphore = SystemSemaphore()

    def __init__(self):
        if not self._symlinkDirInitializationDone:
            self._initializeSymlinkDir()

        self._tmpDir = qt.QTemporaryDir(self._tmpDirTemplatePath())
        self._tmpDir.setAutoRemove(False)

        # Make sure the tmp dir will be cleaned up when application closes
        # Objects delete is not automatically called when Slicer closes
        slicer.app.aboutToQuit.connect(self._cleanupTmpDir)

    def __del__(self):
        self._cleanupTmpDir()

    @classmethod
    def _initializeSymlinkDir(cls):
        """
        Initialize the temporary symbolic directory root for all TemporarySymlink objects and remove previous
        directories if the application was not terminated correctly before.

        If another instance of the application is already running, this step is skipped to avoid corrupting the other
        instance's symlinks.
        """
        # Set initialization to done
        cls._symlinkDirInitializationDone = True

        # Acquire semaphore to initialize symlink path.
        # If semaphore cannot be acquired, another instance of the application is already running and directory
        # shouldn't be touched.
        threadPool = qt.QThreadPool()
        threadPool.start(cls._tmpSymlinkSemaphore)
        threadPool.waitForDone(2000)

        if not cls._tmpSymlinkSemaphore.semaphoreAcquired:
            return

        # Create symbolic directory root if it doesn't exist
        if not os.path.exists(cls._symlinkDirectoryPath()):
            qt.QDir(cls._symlinkDirectoryPath()).mkpath(".")

        # Remove dangling symlinks
        cls._removeDanglingSymlinkDirs()

    @classmethod
    def _removeDanglingSymlinkDirs(cls):
        """Remove previous temporary directories and links if the application was incorrectly terminated previously"""
        for d in os.listdir(cls._symlinkDirectoryPath()):
            d_path = os.path.join(cls._symlinkDirectoryPath(), d)
            symlink_path = os.path.join(d_path, cls._symlinkBaseName)

            # Remove symbolic link if it exists
            try:
                os.unlink(symlink_path)
            except OSError:
                pass

            # Remove directory if it's empty
            try:
                os.rmdir(d_path)
            except OSError:
                pass

    @classmethod
    def _symlinkDirectoryPath(cls):
        """Path to the settings directory containing the temporary symbolic link directories"""
        return os.path.join(os.path.dirname(qt.QSettings().fileName()), "TmpSymlinks")

    @classmethod
    def _tmpDirTemplatePath(cls):
        """Template path for the temporary symlink directories"""
        return os.path.join(cls._symlinkDirectoryPath(), "TmpDir")

    def _cleanupTmpDir(self):
        """Remove the temporary directory and the associated symlink if it exists"""
        if self._tmpDir is not None:
            # Remove symlink before removing TMP Dir to avoid Qt erasing the content of the symlink
            self._removeSymlinkPath()

            # Remove the TMP dir if the symlink was correctly disconnected
            if not os.listdir(self._tmpDir.path()):
                self._tmpDir.remove()

            self._tmpDir = None

    def _removeSymlinkPath(self):
        """Unlink the created symlink if it exists"""
        if os.path.exists(self.getSymlinkPath()):
            os.unlink(self.getSymlinkPath())

    def getSymlinkPath(self):
        """:returns str - path to the symlink. This path may be invalid if the target has not been set yet"""
        return os.path.join(getShortPathToExistingPath(self._tmpDir.path()), self._symlinkBaseName)

    def setTargetDir(self, targetDir):
        """Set the directory to which a symlink needs to be created. Before this call, getSymlinkPath is invalid."""
        if not os.path.isdir(targetDir):
            raise ValueError("Symlink can only be created to an existing directory.")

        self._removeSymlinkPath()

        # If target is on the network, use os.symlink to create the symbolic link.
        # This will require CreateLink privileges for the current user.
        cleaned_target = os.path.normpath(targetDir)
        if r'\\' == cleaned_target[0:2]:
            try:
                os.symlink(cleaned_target, self.getSymlinkPath())
            except OSError:
                warningMessageBox(self.tr("Symbolic link privilege not held"), self.tr(
                    "To access network directories, allow symbolic link privileges for the current user or run the "
                    "application as administrator."))
                raise
        else:
            _winapi.CreateJunction(cleaned_target, self.getSymlinkPath())

    def getSymlinkToExistingPath(self, exitingPath):
        """
        Creates a symlink to an existing file or folder and return the full path to the existing path via the symlink
        """
        dirName, baseName = os.path.split(exitingPath)
        self.setTargetDir(dirName)
        return getShortPathToExistingPath(os.path.join(self.getSymlinkPath(), baseName))

    def getSymlinkToNewPath(self, newPath):
        """
        Creates a symlink to a non existing file or folder and return the full path to the new path via the symlink
        """
        dirName, baseName = os.path.split(newPath)
        self.setTargetDir(dirName)
        return os.path.join(self.getSymlinkPath(), baseName)


class ExportDirectorySettings(object):
    """
    Class responsible for saving and loading the export path from settings
    """

    @classmethod
    def _key(cls):
        return "ExportDirectory"

    @classmethod
    def save(cls, path):
        if os.path.isfile(path):
            path = os.path.dirname(path)

        if not os.path.exists(path):
            return

        qt.QSettings().setValue(cls._key(), path)

    @classmethod
    def load(cls):
        return qt.QSettings().value(cls._key(), "")


def listEveryFileInDirectory(directoryPath, fileExt=""):
    """Recursively lists every path in directoryPath

    :param directoryPath: str - Path of directory from which we want to import the DICOM files
    :param fileExt: str - file extension to filter. If empty will return all the files found
    :return: List[str] Path to every file found in directoryPath
    """
    dicomFilePaths = []

    for rootDirectoryPath, directoryNames, fileNames in os.walk(directoryPath):
        for fileName in fileNames:
            if not fileExt or fileName.endswith(fileExt):
                dicomFilePaths.append(os.path.join(rootDirectoryPath, fileName))
    return dicomFilePaths
