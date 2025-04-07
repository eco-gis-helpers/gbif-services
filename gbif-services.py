import requests
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsFields
)
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QFormLayout, QProgressDialog
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel, QgsCoordinateTransform, QgsCoordinateReferenceSystem
from PyQt5.QtCore import Qt

projInstance = QgsProject.instance()

# Add an incrementing pyqgis group each time the script is run
treeRoot = projInstance.layerTreeRoot()
counter = 0
group_name = 'GBIF Occurrences-' + str(counter)

while treeRoot.findGroup(group_name):
    counter += 1
    group_name = 'GBIF Occurrences-' + str(counter)
pyqgis_group = treeRoot.insertGroup(0, group_name)

# Function to fetch GBIF data
def fetch_gbif_data(url):
    response = requests.get(url)
    return response.json()
    
def transform_geometry_to_epsg4326(geometry, source_crs):
    target_crs = QgsCoordinateReferenceSystem('EPSG:4326')
    transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
    return geometry.transform(transform)

# Function to create and update the progress dialog for GBIF data
def create_progress_dialog(total_estimate, task_name="Fetching GBIF Points..."):
    progress = QProgressDialog(task_name, "Cancel", 0, total_estimate)
    progress.setWindowModality(Qt.WindowModal)  # Modal window so user cannot interact with the map while loading
    progress.setMinimumDuration(0)  # Show dialog immediately
    progress.setValue(0)
    return progress

# Function to create and update the progress dialog for clipping
def create_clipping_progress_dialog(total_count):
    progress = QProgressDialog("Clipping features...", "Cancel", 0, total_count)
    progress.setWindowModality(Qt.WindowModal)  # Modal window so user cannot interact with the map while clipping
    progress.setMinimumDuration(0)
    progress.setValue(0)
    return progress

# Function to create the GBIF Species occurrence point layer with particular attributes
def create_gbif_layer(polygon, layer_id, progress):
    result_layer = QgsVectorLayer('Point?crs=EPSG:4326', f'GBIF Occurrences-{layer_id}', 'memory')
    provider = result_layer.dataProvider()

    fields = QgsFields()
    fields.append(QgsField('gbifID', QVariant.String))
    fields.append(QgsField('species', QVariant.String))
    fields.append(QgsField('country', QVariant.String))
    fields.append(QgsField('eventDate', QVariant.String))
    fields.append(QgsField('catalogNumber', QVariant.String))
    fields.append(QgsField('identifiedBy', QVariant.String))
    fields.append(QgsField('individualCount', QVariant.String))
    provider.addAttributes(fields)
    result_layer.updateFields()

    extent = polygon.boundingBox()
    min_x, min_y = extent.xMinimum(), extent.yMinimum()
    max_x, max_y = extent.xMaximum(), extent.yMaximum()

    # First get the total count
    count_url = (
        'https://api.gbif.org/v1/occurrence/search?'
        f'geometry=POLYGON(({min_x}%20{min_y},{max_x}%20{min_y},{max_x}%20{max_y},{min_x}%20{max_y},{min_x}%20{min_y}))'
        '&limit=0'
    )
    count_data = fetch_gbif_data(count_url)
    total_estimate = min(count_data.get('count', 0), 100000)
    if total_estimate == 0:
        return result_layer, 0

    progress.setMaximum(total_estimate)
    progress.setValue(0)

    offset = 0
    added_records = 0

    while True:
        url = (
            'https://api.gbif.org/v1/occurrence/search?'
            f'geometry=POLYGON(({min_x}%20{min_y},{max_x}%20{min_y},{max_x}%20{max_y},{min_x}%20{max_y},{min_x}%20{min_y}))'
            f'&limit=300&offset={offset}'
        )
        data = fetch_gbif_data(url)

        if 'results' not in data or not data['results']:
            break

        for record in data['results']:
            lat = record.get('decimalLatitude')
            lon = record.get('decimalLongitude')

            if lat is not None and lon is not None:
                feature = QgsFeature()
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
                feature.setAttributes([ 
                    record.get('gbifID', 'Unknown'),
                    record.get('species', 'Unknown'),
                    record.get('country', 'Unknown'),
                    record.get('eventDate', 'Unknown'),
                    record.get('catalogNumber', 'Unknown'),
                    record.get('identifiedBy', 'Unknown'),
                    record.get('individualCount', 'Unknown')
                ])
                provider.addFeatures([feature])
                added_records += 1

                if progress.wasCanceled():
                    return None, 0

                progress.setValue(added_records)
                progress.setLabelText(f"Fetching GBIF Points... {added_records} / {total_estimate}")
                QCoreApplication.processEvents()

        if len(data['results']) < 300:
            break
        offset += 300

    return result_layer, added_records

# function to clip the resulting gbif layer (from the query) with the active polygon(s) layer
def clipping(input_layer, overlay_layer, layer_id):
    # Create clipping progress dialog
    total_features = len([f for f in input_layer.getFeatures()])
    progress = create_clipping_progress_dialog(total_features)

    layer_clip = processing.run('qgis:clip',
        {'INPUT': input_layer,
        'OVERLAY': overlay_layer,
        'OUTPUT': "memory:"}
    )["OUTPUT"]

    layer_clip.setName('result' + str(layer_id))
    layer_clip_result = QgsProject.instance().addMapLayer(layer_clip, False)

    # count the number of results
    feature_count = len([f for f in layer_clip.getFeatures()])
    print(f"{feature_count} GBIF occurrences within polygon layer {layer_id} have been added to the map.")

    # Update the clipping progress bar
    progress.setMaximum(total_features)
    progress.setValue(0)

    feature_idx = 0
    for feature in layer_clip.getFeatures():
        feature_idx += 1
        progress.setValue(feature_idx)
        progress.setLabelText(f"Clipping features... {feature_idx} / {total_features}")
        QCoreApplication.processEvents()

        if progress.wasCanceled():
            print("Script cancelled during clipping.")
            return None

    return pyqgis_group.addLayer(layer_clip_result)

# warning dialog
class WarningDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.warn_str = 'Please note large queries will take longer and may crash QGIS. \n A maximum of 100,000 records can be retrieved at one time.'

        self.setWindowTitle("Query Warning")
        layout = QVBoxLayout()
        
        warning_label = QLabel(self.warn_str)
        layout.addWidget(warning_label)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)
        self.setLayout(layout)

warn_dialog = WarningDialog()

class LayerDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Select Layer for Query")
        self.setMinimumWidth(500)
        self.setMinimumHeight(100)

        self.map_layer_combo_box = QgsMapLayerComboBox()
        self.map_layer_combo_box.setCurrentIndex(-1)
        self.map_layer_combo_box.setFilters(QgsMapLayerProxyModel.PolygonLayer)

        layout = QFormLayout()
        layout.addWidget(self.map_layer_combo_box)
        self.setLayout(layout)
        self.show() 

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def validate_and_accept(self):
        selected_layer = self.map_layer_combo_box.currentLayer()
        if selected_layer:
            self.accept()
        else:
            print("No layer selected!")
            iface.messageBar().pushMessage("Error", "No layer selected!", level=Qgis.Critical)
            raise ValueError("No layer selected!")

    def get_selected_layer(self):
        layer = self.map_layer_combo_box.currentLayer()
        if layer:
            return layer, layer.name()
        return None, None

if warn_dialog.exec_() == QDialog.Accepted:
    print("Warning accepted. Querying GBIF API. Please be patient, the next step can take a few minutes")

    try:
        layer_dialog = LayerDialog()
        if layer_dialog.exec_() == QDialog.Accepted:
            layer, layer_name = layer_dialog.get_selected_layer()
            if layer:
                print(f"Selected Layer: {layer_name}")

            # Iterate through each polygon in the active layer
            for feature in layer.getFeatures():
                layer_id = feature.id()
                
                geometry = feature.geometry()
                source_crs = layer.crs()
                geometry = QgsGeometry(geometry)

                if source_crs.authid() != 'EPSG:4326':
                    geometry.transform(QgsCoordinateTransform(source_crs, QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance()))
                
                # Get the bounding box and count the total records to be fetched
                extent = geometry.boundingBox()
                min_x, min_y = extent.xMinimum(), extent.yMinimum()
                max_x, max_y = extent.xMaximum(), extent.yMaximum()
                
                count_url = (
                    'https://api.gbif.org/v1/occurrence/search?'
                    f'geometry=POLYGON(({min_x}%20{min_y},{max_x}%20{min_y},{max_x}%20{max_y},{min_x}%20{max_y},{min_x}%20{min_y}))'
                    '&limit=0'
                )
                count_data = fetch_gbif_data(count_url)
                total_estimate = min(count_data.get('count', 0), 100000)

                # Initialize progress dialog
                progress = create_progress_dialog(total_estimate)

                # if the polygon is multi-part, we will call the create_gbif_layer function for part of the polygon
                if geometry.isMultipart():
                    for polygon in geometry.asMultiPolygon():
                        result_layer, total_records = create_gbif_layer(QgsGeometry.fromPolygonXY(polygon), layer_id, progress)
                        # as long as there are some results, clip them to the active layer using the clipping function
                        if total_records > 0:
                            clipping(result_layer, layer, layer_id)

                # if the polygon is not multi-part no need to loop through each polygon in the layer
                else:
                    result_layer, total_records = create_gbif_layer(geometry, layer_id, progress)

                    if result_layer is None:
                        print("Script cancelled during GBIF layer creation.")
                        treeRoot.removeChildNode(pyqgis_group)  
                        break

                    if total_records > 0:
                        # as long as there are some results, clip them to the active layer using the clipping function
                        clipping(result_layer, layer, layer_id)

                if progress.wasCanceled():
                    print("Script cancelled during main loop.")
                    treeRoot.removeChildNode(pyqgis_group)  
                    break

                print("Script complete")
        else:
            treeRoot.removeChildNode(pyqgis_group)  
            print("User clicked Cancel. Stopping script")

    except ValueError:
        pass
else:
    treeRoot.removeChildNode(pyqgis_group)
    print("User clicked Cancel. Stopping script.")
