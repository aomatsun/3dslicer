import ctk
import slicer

from RFViewerHomeLib import Signal
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin


class RFViewerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """
    Base widget for the RFViewer modules. Defines convenience signals and methods for configuring and using a module
    integrated int he RFViewer application.

    Signals :
      addProgressBar(str) -> Adds a progress bar with the input string information in the Home module
      removeProgressBar(str) -> Removes progress bar with the input string from the Home module
    """

    def __init__(self, parent):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.addProgressBar = Signal("str")
        self.removeProgressBar = Signal("str")
        self.spacing = 7
        self._dataLoaderWidget = None

    def setLayoutSpacing(self, layout):
        layout.setHorizontalSpacing(self.spacing)

    def addAdvancedSection(self):
        """Creates an "Advanced" collapsible section
        visible only when CTRL+ALT+F12 is pressed
        """
        advancedCollapsibleButton = ctk.ctkCollapsibleButton()
        advancedCollapsibleButton.text = self.tr("Advanced")
        advancedCollapsibleButton.collapsed = True

        self.layout.addWidget(advancedCollapsibleButton)

        return advancedCollapsibleButton

    def setVolumeNode(self, volumeNode):
        """Called when a new volume node is loaded in the application"""
        pass

    def undo(self):
        """Apply undo since last save"""
        self.clean()
        slicer.mrmlScene.SetUndoOn()
        slicer.mrmlScene.Undo()
        self.applyState()
        slicer.mrmlScene.SetUndoOff()
        slicer.mrmlScene.ClearUndoStack()
        self.initializeForUndo()

    def initializeForUndo(self):
        """
        Initialize current scene for undo
        """
        slicer.mrmlScene.SetUndoOn()
        slicer.mrmlScene.ClearUndoStack()
        self.saveState()
        slicer.mrmlScene.SaveStateForUndo()
        # Mrml scene undo needs to be turn off in order to avoid
        # mechanical added into undo stack when a mrml state is updated
        slicer.mrmlScene.SetUndoOff()

    def saveState(self):
        """
        Save the current state of the widget (attributes, UI elements value,...) that
        can be used for the undo or for the saved session.
        Do not save the volume if it's save
        """
        pass

    def applyState(self):
        """Apply the previous saved state to initialize the widget"""
        pass

    def clean(self):
        """Called when session is about to be loaded. Running CLIs are expected to be canceled and disconnected here"""
        pass

    def onSessionAboutToBeSaved(self):
        """Called when the session is about to be saved. Widgets need to save their state to their parameter Node"""
        pass

    def onSessionLoaded(self):
        """Called once session was loaded. Widgets need to reload their previous state from the scene"""
        pass

    def onModuleOpened(self):
        """Called when module is displayed"""
        self.initializeForUndo()

    def getParameterNode(self):
        """
        Return the first available parameter node for this object.
        Parameter singleton tag will correspond to the type of the deriving class.
        Information should be stored in this parameter node to be able to configure the Widget from a reloaded scene.
        """
        className = self.__class__.__name__  # Parameter name will be the name of the deriving class
        nodeType = "vtkMRMLScriptedModuleNode"

        # Return found parameter node if it exists in the scene
        parameterNode = slicer.mrmlScene.GetSingletonNode(className, nodeType)
        if parameterNode:
            return parameterNode

        # Create new parameter node in the scene
        node = slicer.mrmlScene.CreateNodeByClass(nodeType)
        node.UnRegister(None)
        node.SetSingletonTag(className)
        node.SetName(slicer.mrmlScene.GenerateUniqueName(className))
        return slicer.mrmlScene.AddNode(node)

    def setLoadWidget(self, dataLoaderWidget):
        """
        Set the DataLoader widget for the application. This widget always has the information of which volume node is
        loaded.
        """
        self._dataLoaderWidget = dataLoaderWidget
