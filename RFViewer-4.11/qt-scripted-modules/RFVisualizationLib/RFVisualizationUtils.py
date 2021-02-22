import math

import slicer
import vtk


def closestPowerOfTen(_value):
  exp = math.log(_value, 10)
  exp = math.ceil(exp)
  return 10**exp

def getAll3DViewNodes():
  return slicer.util.getNodesByClass('vtkMRMLViewNode')

def truncate(number, digits) -> float:
  stepper = 10.0 ** digits
  return math.trunc(stepper * number) / stepper

def createDiscretizableColorTransferFunctionFromColorPreset(colorPresetName, rangeCTF):
  """
  Create a color transfer function from a color table node
  """
  colorID = slicer.modules.colors.logic().GetColorTableNodeID(colorPresetName)
  colorNode = slicer.util.getNode(colorID)
  nbColors = colorNode.GetNumberOfColors()

  colorTransferFunction = vtk.vtkDiscretizableColorTransferFunction()
  colorTransferFunction.SetColorSpaceToRGB()

  rangeWidth = rangeCTF[1] - rangeCTF[0]
  for i in range(nbColors):
    colorRGBA = [0] * 4
    colorNode.GetColor(i, colorRGBA)
    x = rangeCTF[0] + (i/nbColors) * rangeWidth
    colorTransferFunction.AddRGBPoint(x, colorRGBA[0], colorRGBA[1], colorRGBA[2])

  colorTransferFunction.AdjustRange(rangeCTF)
  colorTransferFunction.Build()
  return colorTransferFunction

def createColorNodeFromVolumePropertyNode(propertyNode, nbOutputColors = 20):
  """
  Create a color table node according to the color transfer function (CTF) of the volume property
  The default number of output colors is set to 20 in order to have enough color
  when the colors of the CTF are variables (ex: red, yellow, blue, red, green => we really need
  to get the second red value)
  The more output colors we have, the closest color table node we have to the property node.
  But, having too many points can also take some times
  """
  colorTransferFunction = propertyNode.GetColor()
  colorTransferFunction.SetColorSpaceToRGB()
  rangeCTF = colorTransferFunction.GetRange()

  rangeWidth = rangeCTF[1] - rangeCTF[0]

  colorNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLColorTableNode')
  colorNode.SetTypeToUser()
  colorNode.SetNumberOfColors(nbOutputColors)

  for i in range(nbOutputColors):
    x = rangeCTF[0] + (i/(nbOutputColors - 1)) * rangeWidth
    colorRGBA = colorTransferFunction.GetColor(x)
    colorNode.SetColor(i, colorRGBA[0], colorRGBA[1], colorRGBA[2])

  return colorNode