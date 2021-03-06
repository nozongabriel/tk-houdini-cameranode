# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

# built-ins
import os

# houdini
import hou
import _alembic_hom_extensions as abc
from PIL import Image

# toolkit
import sgtk
import pyseq

class TkCameraNodeHandler(object):
    """Handle Tk file node operations and callbacks."""


    ############################################################################
    # Class data

    NODE_OUTPUT_PATH_PARM = "filepath"
    """The name of the output path parameter on the node."""

    TK_FILE_NODE_TYPE = "sgtk_file"
    """The class of node as defined in Houdini for the file nodes."""

    ############################################################################
    # Class methods

    @classmethod
    def get_all_tk_camera_nodes(cls):
        """
        Returns a list of all tk-houdini-filenode instances in the current
        session.
        """

        tk_node_type = TkFileNodeHandler.TK_FILE_NODE_TYPE

        return hou.nodeType(hou.ropNodeTypeCategory(), tk_node_type).instances()

    @classmethod
    def get_output_path(cls, node):
        """
        Returns the evaluated output path for the supplied node.
        """

        output_parm = node.parm(cls.NODE_OUTPUT_PATH_PARM)
        path = hou.expandString(output_parm.evalAsString())
        return path

    ############################################################################
    # Instance methods

    def __init__(self, app):
        """Initialize the handler.
        
        :params app: The application instance. 
        
        """

        # keep a reference to the app for easy access to templates, settings,
        # logging methods, tank, context, etc.
        self._app = app

        self._camera_paths = []



    ############################################################################
    # methods and callbacks executed via the OTLs

    # called when the node is created.
    def setup_node(self, node):
        default_name = self._app.get_setting('default_node_name')

        node.setName(default_name, unique_name=True)

        try:
            self._app.log_metric("Create", log_version=True)
        except:
            # ingore any errors. ex: metrics logging not supported
            pass

        #Set initial expressions for transforms
        node.parm('tx').setExpression("detail('./OUT_cam_attrib/', 't', 0)", language=hou.exprLanguage.Hscript)
        node.parm('ty').setExpression("detail('./OUT_cam_attrib/', 't', 1)", language=hou.exprLanguage.Hscript)
        node.parm('tz').setExpression("detail('./OUT_cam_attrib/', 't', 2)", language=hou.exprLanguage.Hscript)

        node.parm('rx').setExpression("detail('./OUT_cam_attrib/', 'r', 0)", language=hou.exprLanguage.Hscript)
        node.parm('ry').setExpression("detail('./OUT_cam_attrib/', 'r', 1)", language=hou.exprLanguage.Hscript)
        node.parm('rz').setExpression("detail('./OUT_cam_attrib/', 'r', 2)", language=hou.exprLanguage.Hscript)

        node.parm('tx').hide(True)
        node.parm('ty').hide(True)
        node.parm('tz').hide(True)

        node.parm('rx').hide(True)
        node.parm('ry').hide(True)
        node.parm('rz').hide(True)

        # get plate from shotgun
        filters = [
            ['project.Project.name', 'is', self._app.context.project['name']],
            ['entity', 'is', self._app.context.entity],
            ['name', 'is', 'undistort-jpeg']
        ]

        order = [{"field_name": "version_number", "direction": "desc"}]
        result = self._app.shotgun.find_one('PublishedFile', filters, ['path', 'name'], order)

        # if undistort-jpeg does not exist check for plate
        if not result:
            self._app.log_info('Did not find undistorted plate, looking for plate!')

            filters = [
                ['project.Project.name', 'is', self._app.context.project['name']],
                ['entity', 'is', self._app.context.entity],
                ['name', 'is', 'plate-jpeg']
            ]

            order = [{"field_name": "version_number", "direction": "desc"}]
            result = self._app.shotgun.find_one('PublishedFile', filters, ['path', 'name'], order)

        if result:
            # set plate path
            plate_path = result['path']['local_path'].replace(os.sep, '/').replace('%04d', '$F4')
            node.parm('vm_background').set(plate_path)

            # set resolution
            plate_path = plate_path.replace('$F4', '*')
            sequences = pyseq.get_sequences(plate_path)
            if sequences:
                first_image_path = sequences[0][0].path
                img = Image.open(first_image_path)
                
                node.parm('baseresx').set(img.size[0])
                node.parm('baseresy').set(img.size[1])

    def control(self, node):
        parent = node.parent()
        geo = node.geometry()

        abc_file = parent.parm('abcFile').evalAsString()
        cam_path = parent.parm('cameraPath').evalAsString()

        if abc_file and abc_file != '' and cam_path != '-1' and cam_path != '':
            frame = parent.parm('samplingFrame').evalAsFloat() / hou.fps()
            
            #Set Transforms
            matrix = hou.Matrix4(abc.getWorldXform(abc_file, cam_path, frame)[0])
            trans = matrix.extractTranslates() * parent.evalParm('scaler')
            rotate = matrix.extractRotates()
            
            geo.setGlobalAttribValue('t',trans)
            geo.setGlobalAttribValue('r',rotate)
            
            #Set Camera Parameters
            cameraDict = abc.alembicGetCameraDict(abc_file, cam_path, frame)

            #Other Attributes
            geo.setGlobalAttribValue('aspect', cameraDict.get('aspect'))

            geo.setGlobalAttribValue('focal', cameraDict.get('focal'))
            geo.setGlobalAttribValue('aperture', cameraDict.get('aperture'))
            
            geo.setGlobalAttribValue('shutter', cameraDict.get('shutter'))
            geo.setGlobalAttribValue('focus', cameraDict.get('focus'))
            geo.setGlobalAttribValue('fstop', cameraDict.get('fstop'))
                
    def camera_menu(self, node):
        abc_file = node.evalParm('abcFile')
        cached_abc_file = node.cachedUserData('abc_file')
        
        if os.path.exists(abc_file):
            if not cached_abc_file or abc_file != cached_abc_file:
                sceneHier = abc.alembicGetSceneHierarchy(abc_file, '/')
                if sceneHier and sceneHier[2]:
                    self._camera_paths = []
                    self._find_camera('/', sceneHier[2])

                #Select first element to select something
                node.parm('cameraPath').set(0)

                menucamera_paths = [x for pair in zip(self._camera_paths, self._camera_paths) for x in pair]

                node.setCachedUserData('abc_file', abc_file)
                node.setCachedUserData('menucamera_paths', menucamera_paths)
                
                return menucamera_paths
        else:
            return []
            
        return node.cachedUserData('menucamera_paths')

    def over_aspect(self, node):
        if node.parm('overAspect').evalAsInt():
            node.parm('aspect').deleteAllKeyframes()
        else:
            node.parm('aspect').setExpression("detail('./OUT_cam_attrib', 'aspect', 0)", language=hou.exprLanguage.Hscript)

    def over_trans(self, node):
        if node.parm('overTrans').evalAsInt():
            node.parm('tx').deleteAllKeyframes()
            node.parm('ty').deleteAllKeyframes()
            node.parm('tz').deleteAllKeyframes()

            node.parm('rx').deleteAllKeyframes()
            node.parm('ry').deleteAllKeyframes()
            node.parm('rz').deleteAllKeyframes()

            node.parm('tx').hide(False)
            node.parm('ty').hide(False)
            node.parm('tz').hide(False)

            node.parm('rx').hide(False)
            node.parm('ry').hide(False)
            node.parm('rz').hide(False)
        else:
            node.parm('tx').setExpression("detail('./OUT_cam_attrib/', 't', 0)", language=hou.exprLanguage.Hscript)
            node.parm('ty').setExpression("detail('./OUT_cam_attrib/', 't', 1)", language=hou.exprLanguage.Hscript)
            node.parm('tz').setExpression("detail('./OUT_cam_attrib/', 't', 2)", language=hou.exprLanguage.Hscript)

            node.parm('rx').setExpression("detail('./OUT_cam_attrib/', 'r', 0)", language=hou.exprLanguage.Hscript)
            node.parm('ry').setExpression("detail('./OUT_cam_attrib/', 'r', 1)", language=hou.exprLanguage.Hscript)
            node.parm('rz').setExpression("detail('./OUT_cam_attrib/', 'r', 2)", language=hou.exprLanguage.Hscript)

            node.parm('tx').hide(True)
            node.parm('ty').hide(True)
            node.parm('tz').hide(True)

            node.parm('rx').hide(True)
            node.parm('ry').hide(True)
            node.parm('rz').hide(True)


    ############################################################################
    # Private methods

    def _find_camera(self, path, children):
        filter_cameras = ['frontShape', 'perspShape', 'sideShape', 'topShape']

        for child in children:
            if child[1] == 'camera' and child[0] not in filter_cameras:
                cam_path = os.path.join(path, child[0])
                # For windows paths
                cam_path = cam_path.replace(os.path.sep, "/")
                self._camera_paths.append(cam_path)
            else:
                self._find_camera(os.path.join(path, child[0]), child[2])