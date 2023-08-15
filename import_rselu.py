#####
# Most of the code is based on logic found in...
#
### GunZ 1
# - RTypes.h
# - RToken.h
# - RealSpace2.h/.cpp
# - RBspObject.h/.cpp
# - RMaterialList.h/.cpp
# - RMesh_Load.cpp
# - RMeshUtil.h
# - MZFile.cpp
# - R_Mtrl.cpp
# - EluLoader.h/cpp
# - LightmapGenerator.h/.cpp
# - MCPlug2_Mesh.cpp
#
### GunZ 2
# - RVersions.h
# - RTypes.h
# - RD3DVertexUtil.h
# - RStaticMeshResource.h
# - RStaticMeshResourceFileLoadImpl.cpp
# - MTypes.h
# - MVector3.h
# - MSVector.h
# - RMesh.cpp
# - RMeshNodeData.h
# - RMeshNodeLoadImpl.h/.cpp
# - RSkeleton.h/.cpp
#
# Please report maps and models with unsupported features to me on Discord: Krunk#6051
#####

import bpy, os, io, math, mathutils
import xml.dom.minidom as minidom
from mathutils import Vector, Matrix

from .constants_gzrs2 import *
from .classes_gzrs2 import *
from .parse_gzrs2 import *
from .readelu_gzrs2 import *
from .lib_gzrs2 import *

def importElu(self, context):
    state = GZRS2State()

    state.convertUnits = self.convertUnits
    state.doCleanup = self.doCleanup
    state.doBoneRolls = self.doBoneRolls
    state.doTwistConstraints = self.doTwistConstraints

    if self.panelLogging:
        print()
        print("=======================================================================")
        print("===========================  RSELU Import  ============================")
        print("=======================================================================")
        print(f"== { self.filepath }")
        print("=======================================================================")
        print()

        state.logEluHeaders = self.logEluHeaders
        state.logEluMats = self.logEluMats
        state.logEluMeshNodes = self.logEluMeshNodes
        state.logVerboseIndices = self.logVerboseIndices
        state.logVerboseWeights = self.logVerboseWeights
        state.logCleanup = self.logCleanup

    elupath = self.filepath
    state.directory = os.path.dirname(elupath)
    state.filename = os.path.basename(elupath).split(os.extsep)[0]

    for ext in XML_EXTENSIONS:
        eluxmlpath = pathExists(f"{ elupath }.{ ext }")

        if eluxmlpath:
            state.xmlEluMats[elupath] = parseEluXML(self, minidom.parse(eluxmlpath), state)
            break

    if readElu(self, elupath, state):
        return { 'CANCELLED' }

    bpy.ops.ed.undo_push()
    collections = bpy.data.collections

    rootMesh = collections.new(state.filename)
    context.collection.children.link(rootMesh)

    setupErrorMat(state)

    for eluMat in state.eluMats:
        setupEluMat(self, eluMat, state)

    if eluxmlpath:
        for xmlEluMat in state.xmlEluMats[elupath]:
            setupXmlEluMat(self, elupath, xmlEluMat, state)

    if state.doCleanup and state.logCleanup:
        print()
        print("=== Elu Mesh Cleanup ===")
        print()

    for eluMesh in state.eluMeshes:
        if eluMesh.meshName.startswith(("Bip01", "Bone")):
            state.gzrsValidBones.add(eluMesh.meshName)

        name = f"{ state.filename }_{ eluMesh.meshName }"

        if eluMesh.isDummy:
            blDummyObj = bpy.data.objects.new(name, None)

            blDummyObj.empty_display_type = 'ARROWS'
            blDummyObj.empty_display_size = 0.1
            blDummyObj.matrix_local = eluMesh.transform

            rootMesh.objects.link(blDummyObj)

            state.blDummyObjs.append(blDummyObj)
            state.blObjPairs.append((eluMesh, blDummyObj))
        else:
            setupElu(self, name, eluMesh, False, rootMesh, context, state)

    processEluHeirarchy(self, state)

    if len(state.gzrsValidBones) > 0:
        state.blArmature = bpy.data.armatures.new("Armature")
        state.blArmatureObj = bpy.data.objects.new(f"{ state.filename }_Armature", state.blArmature)

        state.blArmatureObj.display_type = 'WIRE'
        state.blArmatureObj.show_in_front = True

        rootMesh.objects.link(state.blArmatureObj)

        for viewLayer in context.scene.view_layers:
            viewLayer.objects.active = state.blArmatureObj

        bpy.ops.object.mode_set(mode = 'EDIT')

        reorient = Matrix.Rotation(math.radians(-90.0), 4, 'Z') @ Matrix.Rotation(math.radians(-90.0), 4, 'Y')

        for eluMesh, blMeshOrDummyObj in state.blObjPairs:
            if not eluMesh.meshName in state.gzrsValidBones:
                continue

            blBone = state.blArmature.edit_bones.new(eluMesh.meshName)
            blBone.tail = (0, 0.1, 0)
            blBone.matrix = blMeshOrDummyObj.matrix_world @ reorient

            if eluMesh.isDummy:
                for collection in blMeshOrDummyObj.users_collection:
                    collection.objects.unlink(blMeshOrDummyObj)

            state.blBonePairs.append((eluMesh, blBone))

        for child, childBone in state.blBonePairs:
            if child.meshName == 'Bip01':
                continue

            found = False

            for parent, parentBone in state.blBonePairs:
                if child != parent and child.parentName == parent.meshName:
                    childBone.parent = parentBone
                    found = True

                    break

            if not found:
                self.report({ 'INFO' }, f"GZRS2: Parent not found for elu child bone: { child.meshName }, { child.parentName }")

        for eluMesh, blBone in state.blBonePairs:
            if blBone.name == 'Bip01':
                continue
            elif len(blBone.children) > 0:
                length = 0

                for child in blBone.children:
                    length = max(length, (child.head - blBone.head).length)

                blBone.length = length
            elif blBone.parent is not None:
                blBone.length = blBone.parent.length / 2

            if blBone.parent is not None and (Vector(blBone.parent.tail) - Vector(blBone.head)).length < 0.0001:
                blBone.use_connect = True

        if state.doBoneRolls:
            bpy.ops.armature.select_all(action = 'SELECT')
            bpy.ops.armature.calculate_roll(type = 'GLOBAL_POS_Z')
            bpy.ops.armature.select_all(action = 'DESELECT')

        bpy.ops.object.mode_set(mode = 'OBJECT')

        blPoseBones = state.blArmatureObj.pose.bones

        if state.doBoneRolls and state.doTwistConstraints:
            for parentBone in blPoseBones:
                if 'twist' in parentBone.name.lower():
                    for siblingBone in parentBone.parent.children:
                        if parentBone != siblingBone and len(siblingBone.children) > 0:
                            constraint = parentBone.constraints.new(type = 'TRACK_TO')
                            constraint.target = state.blArmatureObj
                            constraint.subtarget = siblingBone.children[0].name
                            constraint.track_axis = 'TRACK_Y'
                            constraint.up_axis = 'UP_Z'
                            constraint.use_target_z = True
                            constraint.target_space = 'POSE'
                            constraint.owner_space = 'POSE'

                            break

        for child, childObj in state.blObjPairs:
            isBone = child.meshName in state.gzrsValidBones

            if not child.parentName in state.gzrsValidBones or (isBone and child.isDummy):
                continue

            targetName = child.meshName if isBone else child.parentName
            found = False

            for parentBone in blPoseBones:
                if targetName == parentBone.name:
                    transform = childObj.matrix_world

                    childObj.parent = state.blArmatureObj
                    childObj.parent_bone = parentBone.name
                    childObj.parent_type = 'BONE'

                    childObj.matrix_world = transform

                    found = True
                    break

            if not found:
                self.report({ 'INFO' }, f"GZRS2: Bone parent not found: { child.meshName }, { child.parentName }, { child.isDummy }")

        for blMeshObj in state.blMeshObjs:
            modifier = blMeshObj.modifiers.get("Armature", None)

            if modifier:
                modifier.object = state.blArmatureObj

    bpy.ops.object.select_all(action = 'DESELECT')

    return { 'FINISHED' }
