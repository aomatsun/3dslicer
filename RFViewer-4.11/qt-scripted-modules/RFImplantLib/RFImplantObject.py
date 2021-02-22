import slicer, vtk, numpy
import ctypes
from RFVisualizationLib import showInMainViews
from RFViewerHomeLib import jumpSlicesToLocation, getNodeByID, removeNodeFromMRMLScene


class RFImplantObject:
  def __init__(self):
    self.model = None
    self.markupsNode = None

  def __del__(self):
    # Remove matrix observers to avoid views moving on delete event
    if self.markupsNode:
      self.markupsNode.GetInteractionHandleToWorldMatrix().RemoveAllObservers()

    transformNode = getNodeByID(self.model.GetTransformNodeID())
    removeNodeFromMRMLScene(self.model)
    removeNodeFromMRMLScene(self.markupsNode)
    removeNodeFromMRMLScene(transformNode)
    self.modelNode = None
    self.markupNode = None

  @classmethod
  def loadFromParameterDict(cls, paramDict):
    implant = RFImplantObject()
    modelID = paramDict["modelID"]
    markupsNodeID = paramDict["markupsNodeID"]
    markupsDisplayNodeID = paramDict["markupsDisplayNodeID"]
    implant.model = getNodeByID(modelID)

    # Reset loaded markups node to restore context menu for markups placement
    markupsNode = getNodeByID(markupsNodeID)
    if markupsNode:
      markupsNode.SetAndObserveDisplayNodeID(markupsDisplayNodeID)
      markupsNode = cls.resetMarkupsNode(markupsNode)

    implant.markupsNode = markupsNode
    implant.markupsNode.GetDisplayNode().SetOpacity(0)

    if implant.model and implant.markupsNode:
      implant.connectMarkupUpdateToModelTransform(implant.model, implant.markupsNode, implant.modelCenter(implant.model))

    return implant

  @classmethod
  def resetMarkupsNode(cls, markupsNode):
    """Create a copy from input markups node and return the new instance"""
    markupsCopy = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsFiducialNode')
    markupsCopy.CopyContent(markupsNode, False)
    markupsCopy.SetName(markupsNode.GetName())
    markupsCopy.SetHideFromEditors(True)

    # Copy the markups display node
    cls.setupPlacerDisplay(markupsCopy)
    markupsCopy.GetDisplayNode().CopyContent(markupsNode.GetDisplayNode(), False)
    markupsCopy.GetDisplayNode().SetVisibility3D(True)
    markupsCopy.GetDisplayNode().SetHideFromEditors(True)

    # Remove node and display from scene
    removeNodeFromMRMLScene(markupsNode)

    return markupsCopy

  @staticmethod
  def loadFromFilePath(path):
    implant = RFImplantObject()
    implant.model = slicer.util.loadModel(path)
    implant.model.SetUndoEnabled(True)
    implant.model.SetSelectable(True)
    display = implant.model.GetDisplayNode()
    display.SetSliceIntersectionVisibility(True)
    display.SetColor(1, 0, 0)
    display.SetUndoEnabled(True)
    showInMainViews(implant.model)

    implant.markupsNode = implant.setupImplantPlacer(implant.model)
    implant.markupsNode.SetUndoEnabled(True)
    return implant

  def setDisplayVisibility(self, visibility):
    self.model.SetDisplayVisibility(visibility)
    self.markupsNode.SetDisplayVisibility(visibility)

  def enablePlacement(self, enable):
    self.markupsNode.GetDisplayNode().SetHandlesInteractive(enable)
    self.markupsNode.SetLocked(not enable)
  def getIntersect(self):
    lm = slicer.app.layoutManager()
    sliceNames = lm.sliceViewNames()
    pt = [0, 0, 0]

    for sliceName in sliceNames:
      sliceWidget = lm.sliceWidget(sliceName)
      sliceView = sliceWidget.sliceView()      
      if type(sliceView) == slicer.qMRMLSliceView:
        pt[0] = sliceView.getIntersectionRASX()
        pt[1] = sliceView.getIntersectionRASY()
        pt[2] = sliceView.getIntersectionRASZ()
        return pt
  def setupImplantPlacer(self, model):
    markupsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
    markupsNode.HideFromEditorsOn()
    markupsNode.SetName(slicer.mrmlScene.GetUniqueNameByString('ImplantPlacer'))
    markupsNode.SetMarkupLabelFormat('')
    markupsNode.SetUndoEnabled(True)
    self.setupPlacerDisplay(markupsNode)

    # center = self.modelCenter(self, model)
    center = self.getIntersect()
    # self.printlogValues(center[0], center[1], center[2])
    markupsNode.AddFiducial(center[0], center[1], center[2])
    # self.printlogVal(center[0])

    self.connectMarkupUpdateToModelTransform(model, markupsNode, center)
    return markupsNode

  @classmethod
  def setupPlacerDisplay(cls, markupsNode):
    """Create a display node for the input markups node"""
    markupsNode.CreateDefaultDisplayNodes()
    markupsNode.GetDisplayNode().SetUndoEnabled(True)
    markupsNode.GetDisplayNode().SetHandlesInteractive(True)
    markupsNode.GetDisplayNode().SetOpacity(0.2)
    showInMainViews(markupsNode)

  @staticmethod
  def modelCenter(self, model):
      bounds = [0, 0, 0, 0, 0, 0]
      model.GetBounds(bounds)
      return [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]

  @staticmethod
  def applyMatrixToTransform(transform, center):
      def onMatrixModified(matrix, _event=None):
          m = slicer.util.arrayFromVTKMatrix(matrix)
          translation = numpy.identity(4)
          translation[0, 3] = -center[0]
          translation[1, 3] = -center[1]
          translation[2, 3] = -center[2]
          slicer.util.updateTransformMatrixFromArray(transform, m.dot(translation))

          newMatrix = vtk.vtkMatrix4x4()
          transform.GetMatrixTransformToWorld(newMatrix)
          newCenter = [
              newMatrix.GetElement(0, 3),
              newMatrix.GetElement(1, 3),
              newMatrix.GetElement(2, 3)]
          # jumpSlicesToLocation(location=newCenter,centerToLocation=False)

      return onMatrixModified

  def connectMarkupUpdateToModelTransform(self, model, markupsNode, center):
    t = getNodeByID(model.GetTransformNodeID())
    if not t:
        t = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
    t.SetUndoEnabled(True)
    matrix = markupsNode.GetInteractionHandleToWorldMatrix()

    matrix.AddObserver(vtk.vtkCommand.ModifiedEvent, self.applyMatrixToTransform(t, center))
    self.applyMatrixToTransform(t, center)(matrix)
    model.SetAndObserveTransformNodeID(t.GetID())

  def getParameterDict(self):
    return {
      "modelID": self.model.GetID(),
      "markupsNodeID": self.markupsNode.GetID(),
      "markupsDisplayNodeID": self.markupsNode.GetDisplayNode().GetID()
    }
