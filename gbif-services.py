import requests

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsFields
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QFormLayout
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel

projInstance = QgsProject.instance()

# Add an incrementing pyqgis group each time the script is run
treeRoot = projInstance.layerTreeRoot()
counter = 0
group_name = 'GBIF Occurrences-' + str(counter)

while treeRoot.findGroup(group_name):
    counter += 1
    group_name = 'GBIF Occurrences-' + str(counter)
pyqgis_group = treeRoot.insertGroup(0, group_name)

# layer = iface.activeLayer()
# layer_name = layer.name()

# Function to fetch GBIF data
def fetch_gbif_data(url):
    response = requests.get(url)
    return response.json()

def create_gbif_layer(polygon, layer_id):
    # Create an in-memory layer to store the GBIF data
    result_layer = QgsVectorLayer('Point?crs=EPSG:4326', 'GBIF Occurrences-' +str(layer_id), 'memory')
    provider = result_layer.dataProvider()

    # Define the fields for the resulting layer
    # using the occurence search API - here are the fields to choose from
    # https://techdocs.gbif.org/en/openapi/v1/occurrence
    # see "searing occurences" section and the GET /occurence/search dropdown

    #TODO a way to search for one particular species vs. calling in all observations?
    # similiar to the geohub_services scripts - the 'one_service_with_sql.py' script - we could construct a query based on user input

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

    # Get the bounding box of the polygon(s)
    extent = polygon.boundingBox()

    min_x = extent.xMinimum()
    min_y = extent.yMinimum()
    max_x = extent.xMaximum()
    max_y = extent.yMaximum()
    
    # URL for the GBIF API query with bounding box and limit (300)
    base_url = (
        'https://api.gbif.org/v1/occurrence/search?'
        f'geometry=POLYGON(({min_x}%20{min_y},{max_x}%20{min_y},{max_x}%20{max_y},{min_x}%20{max_y},{min_x}%20{min_y}))'
        '&limit=300'
    )
    
    # Fetch records with pagination
    offset = 0
    total_records = 0
    
    while True:
        url = f"{base_url}&offset={offset}"
        data = fetch_gbif_data(url)
        
        if 'results' not in data or not data['results']:
            break  # Exit the loop if no results are returned
        
        for record in data['results']:
            gbif_id = record.get('gbifID', 'Unknown')
            species = record.get('species', 'Unknown')
            country = record.get('country', 'Unknown')
            event_date = record.get('eventDate', 'Unknown')
            catalog_number = record.get('catalogNumber', 'Unknown')
            identifier = record.get('identifiedBy', 'Unknown')
            count = record.get('individualCount', 'Unknown')
            
            lat = record.get('decimalLatitude')
            lon = record.get('decimalLongitude')
            
            if lat is not None and lon is not None:
                feature = QgsFeature()
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
                feature.setAttributes([gbif_id, species, country, event_date, catalog_number, identifier, count])
                provider.addFeatures([feature])
        
        total_records += len(data['results'])

        # Stop if no more data is returned
        if len(data['results']) == 0:
            break

        offset += 300  # move to the next batch of 300 records
    
    return result_layer, total_records

# function to clip the resulting gbif layer (from the query) with the active polygon(s) layer
def clipping(input_layer, overlay_layer, layer_id):
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

    return pyqgis_group.addLayer(layer_clip_result)

# simple warning dialog
class WarningDialog(QDialog):
    def __init__(self, warn_str):
        super().__init__()

        self.setWindowTitle("Query Warning")
        layout = QVBoxLayout()
        
        warning_label = QLabel(warn_str)
        layout.addWidget(warning_label)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)
        self.setLayout(layout)


warn_str = 'Please note large queries will take longer and may crash QGIS. \n A maximum of 100,000 records can be retrieved at one time.'
warn_dialog = WarningDialog(warn_str)

class LayerDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Select Layer for Query")
        self.setMinimumWidth(500)
        self.setMinimumHeight(100)

        self.map_layer_combo_box = QgsMapLayerComboBox()
        self.map_layer_combo_box.setCurrentIndex(-1)
        self.map_layer_combo_box.setFilters(QgsMapLayerProxyModel.VectorLayer)
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
    print("Warning accepted. Querying GBIF API. Please be patient, this step can take a few minutes")

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
                
                # if the polygon is multi-part, we will call the create_gbif_layer function for part of the polygon
                if geometry.isMultipart():
                    for polygon in geometry.asMultiPolygon():

                        result_layer, total_records = create_gbif_layer(QgsGeometry.fromPolygonXY(polygon), layer_id)
                        # as long as there are some results, clip them to the active layer using the clipping function
                        if total_records > 0:
                            clipping(result_layer, layer, layer_id)
                            # print("Clipping layer {layer_id} complete")

                # if the polygon is not multi-part no need to loop through each polygon in the layer
                else:
                    result_layer, total_records = create_gbif_layer(geometry, layer_id)

                    if total_records > 0:
                        # as long as there are some results, clip them to the active layer using the clipping function
                        clipping(result_layer, layer, layer_id)
                        # print("Clipping layer {layer_id} complete")
            
                print("Script complete")
        else:
            treeRoot.removeChildNode(pyqgis_group)  
            print("User clickec Cancel. Stopping script")

    except ValueError:
        pass
else:
    treeRoot.removeChildNode(pyqgis_group)
    print("User clicked Cancel. Stopping script.")
