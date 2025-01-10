// JavaScript Document - main.js
const hamburgerButton = document.querySelector('.hamburger-button');
const mobileNav = document.querySelector('.mobile-nav');

// Get data from data attributes
const bodyElement = document.body;
var alerts = bodyElement.dataset.alerts ? JSON.parse(bodyElement.dataset.alerts) : [];
const loading = bodyElement.dataset.loading === 'True';

hamburgerButton.addEventListener('click', () => {
  mobileNav.classList.toggle('open');
});

document.addEventListener('DOMContentLoaded', function () {
  if (window.innerWidth > 768) {
    if (!mobileNav.classList.contains('open')) {
      mobileNav.classList.add('open');
    }
  }
});
let map; // Declare the variable here
const fillOpacity = 0.5;
let alertLayers = new L.FeatureGroup(); //Create the layer group at the top level
map = L.map('mapid', { // Assign it here, with out the var keyword.
  worldCopyJump: true, // This makes the map wrap seamlessly
  // Removed maxBounds, since this stops the world copy jump from working.

}).setView([51.4779, 0.0015], 5);

map.addLayer(alertLayers); // Add it to the map


// --- Socket.IO ---
let socketUrl;
if (window.location.hostname === 'localhost' || window.location.hostname === '0.0.0.0') {
  socketUrl = 'http://localhost:8080'; // Or your local address and port
} else {
  socketUrl = 'https://weatheralerts.global';
}

const socket = io.connect(socketUrl, {
  timeout: 10000
});


// Handle connection and request initial map data
function connectSocket() {
  socket.on('connect', function () {
    console.log("Socket connected.");
    socket.emit('map_data'); // Request map data on connect
    //displaySuccess("Connected to server via WebSockets!");
  });

  socket.on('connect_error', (error) => {
    console.error("Connection error", error);
    //displayError("Error connecting to server via WebSockets!");
    // Implement retry logic with exponential backoff
    setTimeout(() => {
      connectSocket()
    }, 5000);
  });
  // Handle disconnection
  socket.on('disconnect', function () {
    console.log('Socket disconnected');
    //displayError("Disconnected from server via WebSockets!");
  });
  // Handle reconnection
  socket.on('reconnect', function () {
    console.log("Socket reconnected!");
    //displaySuccess("Reconnected to server via WebSockets!");
    socket.emit('map_data'); // Re-request data on reconnect
  });

  // Handle incoming map data updates from server
  socket.on('map_data_update', function (data) {
    console.log("Received map data update via SocketIO:", data);
    if (data && data.map_data) {
      // Clear existing layers, only incident alerts
      map.eachLayer(function (layer) {
        if (layer instanceof L.GeoJSON && layer.options && layer.options.onEachFeature && !layer.alertZone) {
          map.removeLayer(layer);
        }
      });
      displayAlerts(data.map_data.alerts);
		        // Update the global alerts variable
        alerts = data.map_data.alerts;

        // Recalculate statistics and update the display
        updateAlertStatistics(alerts);
		

      // Display the cached timestamp
      const timestampElement = document.getElementById('cache-timestamp');
      if (timestampElement) {
        timestampElement.textContent = data.cache_timestamp ? moment(data.cache_timestamp).format('YYYY-MM-DD HH:mm:ss UTC') : "No timestamp available";
      } else {
        console.warn("cache-timestamp element not found in DOM")
      }
    } else {
      console.error("Error: Invalid map data received.");
      displayError("Error: Invalid map data received via WebSockets.");
    }
  });
}
connectSocket();

function updateAlertStatistics(alerts) {
    let alertCount = 0;
    let alertCounts = {};
    let dateRange = "";

    if (alerts) {
        alertCount = alerts.length;

        for (const alert of alerts) {
            const severity = alert.severity || "Unknown";
            alertCounts[severity] = (alertCounts[severity] || 0) + 1;
            let startDate = new Date(Math.min(...alerts.map(a => a.start * 1000)));
            let endDate = new Date(Math.max(...alerts.map(a => a.end * 1000)));
            dateRange = `${startDate.toLocaleDateString()} - ${endDate.toLocaleDateString()}`;
        }
    }

    $('#alert-count p').html(`There are <b>${alertCount}</b> live alerts in place covering the period <b>${dateRange}</b>`);
    $('.square').text(alertCount);
    $('.square:eq(1)').text(alertCounts.Minor || 0);
    $('.square:eq(2)').text(alertCounts.Moderate || 0);
    $('.text-severe-extreme:eq(0)').text(alertCounts.Severe || 0);
    $('.text-severe-extreme:eq(1)').text(alertCounts.Extreme || 0);

}
function createAlertTooltipContent(alert) {
  const severityColor = {
    Minor: "#00FF00",
    Moderate: "#FFA500",
    Severe: "#FF0000",
    Extreme: "#313131",
    Unknown: "#313131"
  } [alert.severity] || "#FF0000";
  return `<div class="my-tooltip" data-severity="${alert.severity}" style="border-color: ${severityColor}">`
    + `<div class="underline"><h2>Alert Details</h2></div>`
    //+ `<p><b>Message ID:</b> ${alert.mongo_id}</p>`
    + `<p><b>Message Type:</b> ${alert.msg_type}</p>`
    + `<p><b>Categories:</b> ${alert.categories.join(', ')}</p>`
    + `<p><b>Urgency:</b> ${alert.urgency}</p>`
    + `<p><b>Severity:</b> ${alert.severity}</p>`
    + `<p><b>Certainty:</b> ${alert.certainty}</p>`
    + `<p><b>Start:</b> ${moment.unix(alert.start).format('YYYY-MM-DD HH:mm:ss UTC')}</p>`
    + `<p><b>End:</b> ${moment.unix(alert.end).format('YYYY-MM-DD HH:mm:ss UTC')}</p>`
    + `<p><b>Sender:</b> ${alert.sender}</p>`
    + `<div class="underline"><h3>Description</h3></div>`
    + `<div class="description-text"><p>${alert.description}</p></div>`
    + `<div style="text-align: right; margin-top: 10px;">`
  	//+ `<button type="button" class="btn btn-primary h-spaced-buttons send-single-alert-snapshot" data-alert-key="${alert.mongo_id}">Send Single Alert</button>`
    + (alert.language !== 'en' && alert.language !== 'en-GB' && alert.language !== 'en-US' && alert.language !== 'en-JM' && alert.language !== 'en-CA' && alert.language !== 'en-AU'
      ? `<button type="submit" class="btn btn-primary h-spaced-buttons translate">Translate to EN</button>` : "")
    + `<button type="button" class="btn btn-primary h-spaced-buttons close-popup">Close Alert</button>`
    +
    `</div>`
    + `</div>`;
}

$(document).on('click', '.close-popup', function () {
  $(this).closest('.leaflet-popup').remove();
});

function displayAlerts(incidentAlerts, alert_name) {
  const maxWidth = 600;
  console.log("Displaying alerts:", incidentAlerts);
  if (!incidentAlerts) {
    console.warn("No alerts data to display.");
    return;
  }
  if (incidentAlerts.length === 0) {
    console.log("No alerts to display for this area.");
    $("#alertModalTitle").text(`No Active Alerts for ${alert_name ? alert_name : 'this zone'}`);
    $("#alertModalBody").html('<p>No active alerts for this zone.</p>');
    $("#alertModal").modal('show');
    return;
  }

  let modalBodyContent = '<ul>';

  incidentAlerts.forEach(alert => {
    modalBodyContent += `<li>
            <b>Start:</b> ${new Date(alert.start * 1000).toLocaleString()} <br>
            <b>End:</b> ${new Date(alert.end * 1000).toLocaleString()} <br>
            <b>Severity:</b> ${alert.severity} <br>
            <b>Description:</b> ${alert.description} <br>
          </li>`;

    let geoJsonGeometry = alert.geometry;

    if (geoJsonGeometry && geoJsonGeometry.type === 'Polygon' && geoJsonGeometry.coordinates && Array.isArray(geoJsonGeometry.coordinates)) {
      //Reverse all co-ordinates
      geoJsonGeometry.coordinates = geoJsonGeometry.coordinates.map(ring => {
        return ring.map(coord => [coord[0], coord[1]]); //Reverse single ring
      });
    }


    // Wrap geometry in a GeoJSON Feature
    const geoJsonFeature = {
      type: "Feature",
      geometry: geoJsonGeometry,
      properties: alert // Keep any properties
    };

    L.geoJSON(geoJsonFeature, {
      style: function () {
        return {
          fillColor: alert.color,
          color: '#000',
          weight: 1,
          dashArray: '',
          fillOpacity: fillOpacity
        };
      },
      onEachFeature: function (feature, layer) {
        layer.bindPopup(createAlertTooltipContent(alert), {
          autoClose: false,
          maxWidth: maxWidth
        });
        layer.on('click', function () {
          this.openPopup();
          const severity = $(this._popup._content).find('.my-tooltip').data('severity');
          const popupWrapper = this._popup._wrapper;
          const severityColor = {
            Minor: "#00FF00",
            Moderate: "#FFA500",
            Severe: "#FF0000",
            Extreme: "#313131",
            Unknown: "#313131"
          } [severity] || "#FF0000";
          $(popupWrapper).find('.leaflet-popup-content-wrapper').addClass('severity-popup').css('background', severityColor + ' !important');
        });
        layer.on({
          mouseover: function () {
            this.setStyle({
              fillOpacity: 0.2
            });
          },
          mouseout: function () {
            this.setStyle({
              fillOpacity: fillOpacity
            });
          }
        });
      }
    }).addTo(alertLayers);
  });
  modalBodyContent += '</ul>';

  $("#alertModalTitle").text(`Active Alerts for ${alert_name ? alert_name : 'this zone'}`);
  $("#alertModalBody").html(modalBodyContent);
  $("#alertModal").modal('show');
}

$(document).ready(function () {

  console.log("Alerts:", alerts);
  console.log("Document ready");
  console.log($('#createAlertModal').length); // Check if element exists

  const fillOpacity = 0.5;
  const maxWidth = 600;


  const voyagerLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  });

  const darkLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  });
  voyagerLayer.addTo(map);


  // Function to process map data and handle alerts
  function processMapData(data) {
    if (data && data.map_data) {
      //Clear the map of incident alerts only
      map.eachLayer(function (layer) {
        if (layer instanceof L.GeoJSON && layer.options && layer.options.onEachFeature && !layer.alertZone) {
          map.removeLayer(layer);
        }
      });

      incidentAlerts = data.map_data.alerts; // Update the global alerts variable
      hideLoadingMessage();
    } else {
      console.error("Error: Invalid map data received.");
      //displayError("Error: Invalid map data received.");
    }
  }


  function getAlertsForZone(alertData) {
    const geometry = alertData.geometry;
    console.log("getAlertsForZone called with geometry: ", geometry);
    $.ajax({
      type: "GET",
      url: "/get_alerts_for_zone",
      data: {
        geometry: JSON.stringify(geometry)
      },
      success: function (response) {
        console.log("Alerts data received:", response);
        if (response && response.alerts && response.alerts.length > 0) {
          const transformedAlerts = response.alerts.map(alert => ({
            ...alert,
            geometry: alert.geometry || alertData.geometry,
            color: alert.color, // Include color if it's in the response
          }));
          let alertName = null;
          if (alertData && alertData.alert_name) {
            alertName = alertData.alert_name;
          } else if (alertData.alert_name) {
            alertName = alertData.alert_name;
          }


        } else {
          //displayError("No alerts found for this area.");
        }
      },
      error: function (xhr, status, errorThrown) {
        console.error("Error fetching alerts for zone:", status, errorThrown, xhr);
        let errorMessage = "Error fetching alerts for zone.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          errorMessage = xhr.responseJSON.error;
        }
        displayError(errorMessage);
      }
    });
  }


  function handleAlert(alert) {
    L.geoJSON(alert.geometry, {
      style: function () {
        return {
          fillColor: alert.color,
          color: '#000',
          weight: 1,
          dashArray: '',
          fillOpacity: fillOpacity
        };
      },
      onEachFeature: function (feature, layer) {
        layer.bindPopup(createAlertTooltipContent(alert), {
          autoClose: false,
          maxWidth: maxWidth
        });
        layer.on('click', function () {
          this.openPopup();
          const severity = $(this._popup._content).find('.my-tooltip').data('severity');
          const popupWrapper = this._popup._wrapper;
          const severityColor = {
            Minor: "#00FF00",
            Moderate: "#FFA500",
            Severe: "#FF0000",
            Extreme: "#313131",
            Unknown: "#313131"
          } [severity] || "#FF0000";
          $(popupWrapper).find('.leaflet-popup-content-wrapper').addClass('severity-popup').css('background', severityColor + ' !important');
        });
        layer.on({
          mouseover: function () {
            this.setStyle({
              fillOpacity: 0.2
            });
          },
          mouseout: function () {
            this.setStyle({
              fillOpacity: fillOpacity
            });
          }
        });
      }
    }).addTo(alertLayers); // add the new layer to the new alert layer group
  }


  function loadAlerts() {
    $.ajax({
      type: "GET",
      url: "/get_user_alerts",
      success: function (response) {
        drawnItems.clearLayers();
        if (response.alerts && response.alerts.length > 0) {
          response.alerts.forEach(addAlertToMap);
          map.fitBounds(drawnItems.getBounds());
        } else {
          displayError("No active alert zones found for this user.");
        }
      },
      error: function (xhr, status, errorThrown) {
        console.error("AJAX error:", status, errorThrown, xhr);
        let errorMessage = "Error fetching active alert zones.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          errorMessage = xhr.responseJSON.error;
        }
        displayError(errorMessage);
      }
    });
  }

  let drawnItems = new L.FeatureGroup();
  let drawingLayer = new L.FeatureGroup();
  map.addLayer(drawnItems);
  map.addLayer(drawingLayer);

  let drawControl = new L.Control.Draw({
    position: 'topleft',
    draw: {
      polygon: {
        allowIntersection: false,
        showArea: true,
        drawError: {
          color: '#b00b00',
          timeout: 1000
        },
        shapeOptions: {
          color: '#bada55'
        }
      },
      rectangle: {
        shapeOptions: {
          color: '#bada55'
        }
      },
      polyline: false,
      circle: false,
      marker: false,
      circlemarker: false
    },
    edit: {
      featureGroup: drawnItems
    }
  });
  map.addControl(drawControl);

  $('#openModalButton').click(function () {
    $('#createAlertModal').modal('show');
  });


  function handleAlert(alert) {
    L.geoJSON(alert.geometry, {
      style: function () {
        return {
          fillColor: alert.color,
          color: '#000',
          weight: 1,
          dashArray: '',
          fillOpacity: fillOpacity
        };
      },
      onEachFeature: function (feature, layer) {
        layer.bindPopup(createAlertTooltipContent(alert), {
          autoClose: false,
          maxWidth: maxWidth
        });
        layer.on('click', function () {
          this.openPopup();
          const severity = $(this._popup._content).find('.my-tooltip').data('severity');
          const popupWrapper = this._popup._wrapper;
          const severityColor = {
            Minor: "#00FF00",
            Moderate: "#FFA500",
            Severe: "#FF0000",
            Extreme: "#313131",
            Unknown: "#313131"
          } [severity] || "#FF0000";
          $(popupWrapper).find('.leaflet-popup-content-wrapper').addClass('severity-popup').css('background', severityColor + ' !important');
        });
        layer.on({
          mouseover: function () {
            this.setStyle({
              fillOpacity: 0.2
            });
          },
          mouseout: function () {
            this.setStyle({
              fillOpacity: fillOpacity
            });
          }
        });
      }
    }).addTo(map);
  }

  function hideLoadingMessage() {
    $('#loading-message').addClass('hidden');
    $('#loading-screen').addClass('hidden');
  }

  function formatKeywords(text) {
    const keywords = ["Language", "Event", "Headline", "Instruction"];
    let formattedText = text;
    for (let keyword of keywords) {
      const reg = new RegExp(`(${keyword}:)(.*?)(\n|$)`, 'g');
      formattedText = formattedText.replace(reg, `<p><b>$1</b> $2</p>`);
    }
    return formattedText;
  }


  const loadingScreen = $('#loading-screen');
  const loadingMessage = $('#loading-message');

  if (loading) {
    loadingScreen.addClass('shown');
    loadingMessage.addClass('shown');
  }

  loadingScreen.addClass('hidden');
  loadingMessage.addClass('hidden');


  if ($('#createAlertModal').length > 0) {
    $('#createAlertButton').click(function () {
      setTimeout(function () {
        console.log("Showing modal (setTimeout)");
        $('#createAlertModal').modal('show');
      }, 100);
    });

    let previewLayer = null; //Add a global variable to hold the existing previewLayer

    function updateAlertZonePreview() {
      const geojson = drawnItems.toGeoJSON();

      // Remove the previous preview layer if it exists
      if (previewLayer) {
        map.removeLayer(previewLayer);
        previewLayer = null;
      }

      if (geojson.features.length > 0) {
        // The preview layer will not be added to the map, only the HTML
        $('#alertZonePreview').html(`<p><b>Preview of your alert zone:</b></p>`);
      } else {
        $('#alertZonePreview').html('<p>Draw an alert zone on the map.</p>');
      }
    }

    map.on('draw:created', function (e) {
      console.log("draw:created event:", e);
      const layer = e.layer;

      // Clear the drawing layer before adding a new layer
      drawingLayer.clearLayers();
      drawingLayer.addLayer(layer);
      drawnItems.addLayer(layer);
      updateAlertZonePreview();

      // Zoom to the alert zone
      if (layer) {
        if (layer instanceof L.Polygon) {
          map.fitBounds(layer.getBounds(), {
            padding: [20, 20]
          });
        } else if (layer instanceof L.Rectangle) {
          map.fitBounds(layer.getBounds(), {
            padding: [20, 20]
          });
        }
      }
      // **New code to open the modal after drawing**
      setTimeout(function () {
        $('#createAlertModal').modal('show');
      }, 100); // Add a small delay to ensure everything is ready
    });

    map.on('draw:edited', function (e) {
      console.log("draw:edited event:", e);
      updateAlertZonePreview();
    });

    map.on('draw:deleted', function (e) {
      console.log("draw:deleted event:", e);
      updateAlertZonePreview();
    });

    // Alert creation handler
    $('#createAlertSubmit').click(function () {
      const alertName = $('#alertName').val();
      const description = $('#alertDescription').val();

      if (!alertName) {
        displayError("Please enter an alert name.");
        return;
      }

      const geojson = drawingLayer.toGeoJSON(); // Get GeoJSON from drawingLayer
      console.log("GeoJSON data being sent:", geojson);

      if (geojson.features.length === 0) {
        displayError("Please draw an alert zone on the map first.");
        return;
      }

      // Basic GeoJSON validation
      if (!geojson.features[0].geometry || !geojson.features[0].geometry.coordinates || geojson.features[0].geometry.coordinates.length === 0) {
        displayError('Invalid GeoJSON data. Please try again.');
        return;
      }


      $.ajax({
        type: "POST",
        url: "/create_alert_zone",
        contentType: "application/json",
        data: JSON.stringify({
          geojson: geojson,
          alert_description: description,
          alert_name: alertName
        }),
        success: function (response) {
          displaySuccess(`Alert '${alertName}' created successfully! (ID: ${response.alert_id})`);

          // Zoom to the newly created alert zone
          if (drawingLayer.getLayers().length > 0) {
            const drawnLayer = drawingLayer.getLayers()[0]; //get the current drawn layer.
            if (drawnLayer instanceof L.Polygon || drawnLayer instanceof L.Rectangle) {
              map.fitBounds(drawnLayer.getBounds(), {
                padding: [20, 20]
              });
            }
          }

          drawnItems.clearLayers(); // Clear the drawnItems layer
          // Use the Leaflet.draw tools to remove any existing drawings
          if (map._toolbars && map._toolbars.draw && map._toolbars.draw._activeMode) {
            map._toolbars.draw._activeMode.disable();
          }
          $('#createAlertModal').modal('hide');
          $('#alertName').val('');
          $('#alertDescription').val('');
          $('#alertZonePreview').empty();
          // Optionally set the initial state:
          setEmailAlertState(response.alert_id);

          // Load the alerts
          loadAlerts();
          // Ensure the button says 'Hide Active Notification Zones'
          showAlertsButton.text("Hide Active Alert Notification Zones");

        },
        error: function (xhr, status, errorThrown) {
          console.error("Error creating alert:", status, errorThrown, xhr.responseText, xhr);
          let errorMessage = "Error creating alert.";
          if (xhr.responseJSON && xhr.responseJSON.error) {
            errorMessage = `Error creating alert: ${xhr.responseJSON.error}`;
          }
          displayError(errorMessage);
        }
      });
    });
  } else {
    console.error("Modal element not found!");
  }


  let showAlerts = true;
  const showAlertsButton = $('#showAlertsButton');

  // Set initial button state and text on load
  if (showAlerts) {
    loadAlerts(); // Load alerts if it's initially set to true
    showAlertsButton.text("Hide Active Alert Notification Zones");
  } else {
    showAlertsButton.text("Show Active Alert Notification Zones");
  }

  showAlertsButton.click(function () {
    showAlerts = !showAlerts; // Toggle showAlerts state
    if (showAlerts) {
      loadAlerts(); // Separate function to load alerts
      showAlertsButton.text("Hide Active Alert Notification Zones");
    } else {
      drawnItems.clearLayers(); // Clear the drawn items
      drawingLayer.clearLayers(); // Clear the drawing layer
      showAlertsButton.text("Show Active Alert Notification Zones");
    }
  });

  function loadAlerts() {
    $.ajax({
      type: "GET",
      url: "/get_user_alerts",
      success: function (response) {
        drawnItems.clearLayers();
        if (response.alerts && response.alerts.length > 0) {
          response.alerts.forEach(addAlertToMap);
          map.fitBounds(drawnItems.getBounds());
        } else {
          displayError("No active alert zones found for this user.");
        }
      },
      error: function (xhr, status, errorThrown) {
        console.error("AJAX error:", status, errorThrown, xhr);
        let errorMessage = "Error fetching active alert zones.";
        if (xhr.responseJSON && xhr.responseJSON.error) {
          errorMessage = xhr.responseJSON.error;
        }
        displayError(errorMessage);
      }
    });
  }

  function addAlertToMap(alert) {
    return new Promise((resolve, reject) => {
      const geometry = alert.geometry || {};
      const color = alert.color || '#9C3FFE';

      if (geometry.type && geometry.coordinates && geometry.coordinates.length > 0) {
        let leafletGeoJSON;
        if (geometry.type === 'Polygon') {
          leafletGeoJSON = L.polygon(geometry.coordinates[0].map(coord => [coord[1], coord[0]]), {
            color: '#000',
            weight: 2,
            fillColor: color,
            fillOpacity: 0.7
          });
        } else if (geometry.type === 'Point') {
          leafletGeoJSON = L.marker([geometry.coordinates[1], geometry.coordinates[0]]);
        } else {
          console.warn("Unsupported geometry type:", geometry.type);
          reject("Unsupported geometry type"); // Reject the promise if unsupported
          return;
        }

        leafletGeoJSON.bindPopup(createAlertZonePopupContent(alert), {
          autoClose: false,
          maxWidth: maxWidth
        });
        leafletGeoJSON.on({
          mouseover: function (e) {
            e.target.setStyle({
              fillOpacity: 0.4
            });
          },
          mouseout: function (e) {
            e.target.setStyle({
              fillOpacity: 0.2
            });
          }
        });
        leafletGeoJSON.addTo(drawnItems);
        leafletGeoJSON.alertId = alert._id;
        leafletGeoJSON.alertData = alert;
        leafletGeoJSON.alertZone = true; // Mark this as an alert notification zone layer
        resolve();
        leafletGeoJSON.on('click', function (e) {
          console.log("Shape Clicked at :", leafletGeoJSON.alertData.geometry); // Access the geometry from leafletGeoJSON.alertData
          getAlertsForZone(leafletGeoJSON.alertData);
        });
      } else {
        console.warn("Invalid geometry data in alert:", alert);
        reject("Invalid geometry data");
      }
    });
  }


  function createAlertZonePopupContent(alert) {
    let uniqueId = 'email-alerts-' + alert._id.replace(/[^a-zA-Z0-9]/g, ''); // Ensure a valid ID
    let retrieveButton = `<button class="btn btn-primary h-spaced-buttons retrieve-alert-button" data-alert-id="${alert._id}">Send Alert Zone Snapshot</button>`;
    let deleteButton = `<button class="btn btn-danger h-spaced-buttons delete-alert-button" data-alert-id="${alert._id}">Delete Alert Notification Zone</button>`;
    let emailAlertToggle = `<p>Enable e-mail alerts <input type="checkbox" class="email-alerts-popup" id="${uniqueId}" data-alert-id="${alert._id}"/></p>`;

    return `<div class="my-tooltip"><h3><b>Alert Zone Name:</b> ${alert.alert_name}</h3><p><b>Alert Zone Description:</b> ${alert.alert_description}</p></div>` + emailAlertToggle + retrieveButton + deleteButton;
  }
  map.on('popupopen', function (e) {
    const popup = e.popup;
    const popupContent = popup.getElement();
    const retrieveButton = popupContent.querySelector('.retrieve-alert-button');
    const deleteButton = popupContent.querySelector('.delete-alert-button');
    const layer = e.popup._source;
    const alertId = layer.alertId;


    if (layer.alertZone) { //Check if it's an alert zone popup.

      console.log("Current alerts:", alerts);

      //Initialize switchery for any new popups
      let elems = Array.prototype.slice.call(popupContent.querySelectorAll('.email-alerts-popup'));
      elems.forEach(function (html) {
        var switchery = new Switchery(html, {
          color: '#1AB394',
          size: 'small'
        });
      });

      // Get and Set Email alert state.
      const emailAlertSwitch = popupContent.querySelector('.email-alerts-popup');
      $.ajax({
        type: "GET",
        url: "/get_user_email_alert_state",
        data: {
          user_id: alertId
        },
        success: function (response) {
          if (response.email_alerts_enabled === true) {
            emailAlertSwitch.checked = true;
            emailAlertSwitch.nextElementSibling.querySelector('small').style.left = '16px';
            emailAlertSwitch.nextElementSibling.querySelector('small').style.transition = 'all 0.1s ease';
          } else {
            emailAlertSwitch.checked = false;
            emailAlertSwitch.nextElementSibling.querySelector('small').style.left = '0px';
            emailAlertSwitch.nextElementSibling.querySelector('small').style.transition = 'all 0.1s ease';
          }
        },
        error: function (xhr, status, errorThrown) {
          console.error("Error fetching email alert state:", status, errorThrown, xhr);
        }
      });
    }

    if (retrieveButton) {
      retrieveButton.addEventListener('click', function () {
        console.log("Send Alert Snapshot Clicked at alert ID :", alertId);
        $.ajax({
          type: "POST",
          url: "/send_alert_snapshots",
          data: {
            alert_id: alertId
          }, // <--- Add alert_id to data
          success: function (response) {
            displaySuccess(response.message);
          },
          error: function (xhr, status, errorThrown) {
            console.error("Error sending alert snapshots:", status, errorThrown, xhr);
            let errorMessage = "Error sending alert snapshots.";
            if (xhr.responseJSON && xhr.responseJSON.error) {
              errorMessage = xhr.responseJSON.error;
            }
            displayError(errorMessage);
          }
        });
      });
    }

    if (deleteButton) {
      deleteButton.addEventListener('click', function () {
        if (confirm(`Are you sure you want to delete alert zone with ID: ${alertId}?`)) {
          $.ajax({
            type: "DELETE",
            url: `/delete_alert_zone/${alertId}`,
            success: function (response) {
              displaySuccess("Alert zone deleted successfully!");
              drawnItems.removeLayer(layer);
              popup.remove();
            },
            error: function (error) {
              displayError("Error deleting alert zone: " + error.responseText);
              console.error("Error:", error);
            }
          });
        }
      });
    }
  });

  $('#deleteAllAlertsButton').click(function () {
    if (confirm("Are you sure you want to delete ALL your active alert zones?")) {
      $.ajax({
        type: "DELETE",
        url: "/delete_all_alert_zones",
        success: function (response) {
          displaySuccess(response.message);
          drawnItems.clearLayers(); // Only clear the user's drawn zones, not all alerts
          // Optionally, update alert count display if needed:
          $('#alert-count p').text(`There are ${response.deleted_count} active alerts.`); //Update count
        },
        error: function (xhr, status, errorThrown) {
          console.error("Error deleting all alert zones:", status, errorThrown, xhr);
          let errorMessage = "Error deleting alert zones.";
          if (xhr.responseJSON && xhr.responseJSON.error) {
            errorMessage = xhr.responseJSON.error;
          }
          displayError(errorMessage);
        }
      });
    }
  });

  $('.lightdark-switch').change(function () {
    if ($(this).is(':checked')) {
      darkLayer.addTo(map);
      map.removeLayer(voyagerLayer);
      $('#top-right-panel').css({
        'background-color': '#333',
        'color': '#eee',
        'border': '1px solid #ccc'
      });
      $('.square').css({
        'color': '#000000'
      });
      $('.text-severe-extreme').css({
        'color': '#FFFFFF'
      });
      $('.my-tooltip').css({
        'color': '#FFFFFF',
        'background-color': '#333'
      });
      $('body').css('color', '#eee');
    } else {
      voyagerLayer.addTo(map);
      map.removeLayer(darkLayer);
      $('#top-right-panel').css({
        'background-color': 'white',
        'color': '#000000',
        'border': '1px solid #000000'
      });
      $('.square').css({
        'color': '#000000'
      });
      $('.text-severe-extreme').css({
        'color': '#FFFFFF'
      });
      $('.my-tooltip').css({
        'color': '#000000',
        'background-color': '#FFFFFF'
      });
      $('body').css('color', '#333');
    }
  });

  $(document).on('click', '.translate', function () {
    var descriptionElement = $(this).parents('.my-tooltip').find('.description-text');
    var text = descriptionElement.text();

    if (!descriptionElement.data('translated')) {
      $.get('/translate', {
        text: text
      }, function (response) {
        if (response && response.translated_text) {
          var formattedText = formatKeywords(response.translated_text);
          descriptionElement.html(formattedText);
          descriptionElement.data('translated', true);

        }
      });
    }
  });
$(document).on('click', '.send-single-alert-snapshot', function () {
  const alertKey = $(this).data('alert-key');
  console.log("Send single alert snapshot clicked for alert key:", alertKey);
  $.ajax({
    type: "POST",
    url: "/send_single_alert_snapshot",
    data: {
      alert_key: alertKey,
    },
    success: function (response) {
      displaySuccess(response.message);
    },
    error: function (xhr, status, errorThrown) {
      console.error("Error sending single alert snapshot:", status, errorThrown, xhr);
      let errorMessage = "Error sending single alert snapshot.";
      if (xhr.responseJSON && xhr.responseJSON.error) {
        errorMessage = xhr.responseJSON.error;
      }
      displayError(errorMessage);
    }
  });
});
	
  var elems = Array.prototype.slice.call(document.querySelectorAll('.lightdark-switch'));
  elems.forEach(function (html) {
    var switchery = new Switchery(html);
  });

  var elems = Array.prototype.slice.call(document.querySelectorAll('.email-alerts'));
  elems.forEach(function (html) {
    var switchery = new Switchery(html);
  });


  // --- Utility Functions ---
  function displayError(message) {
    console.error("Error: " + message); //Added this log
    alert("Error: " + message);
  }

  function displaySuccess(message) {
    console.log("Success: " + message); //Added this log
    alert("Success: " + message)
  }
});


$('#createAlertModal').on('show.bs.modal', function (e) {
  const emailAlertSwitch = $(this).find('.email-alerts');
  const alertId = emailAlertSwitch.data('alert-id');
  //Get the current users saved switch state if it exists.
  $.ajax({
    type: "GET",
    type: "GET",
    url: "/get_user_email_alert_state",
    data: {
      user_id: alertId
    },
    success: function (response) {
      if (response.email_alerts_enabled === true) {
        emailAlertSwitch.prop('checked', true);
        emailAlertSwitch.next('.switchery').css('background-color', 'rgb(100, 189, 99)');
        emailAlertSwitch.next('.switchery').find('small').css('left', '16px');
        emailAlertSwitch.next('.switchery').find('small').css('transition', 'all 0.1s ease');
      } else {
        emailAlertSwitch.prop('checked', false);
        emailAlertSwitch.next('.switchery').css('background-color', '');
        emailAlertSwitch.next('.switchery').find('small').css('left', '0px');
        emailAlertSwitch.next('.switchery').find('small').css('transition', 'all 0.1s ease');
      }
    },
    error: function (xhr, status, errorThrown) {
      console.error("Error fetching email alert state:", status, errorThrown, xhr);
    }
  });
});

$(document).on('change', '.email-alerts-popup', function () {
  const isChecked = $(this).prop('checked');
  const alertId = $(this).data('alert-id');
  $.ajax({
    type: "POST",
    url: "/update_user_email_alert_state",
    contentType: "application/json",
    data: JSON.stringify({
      user_id: alertId,
      email_alerts_enabled: isChecked
    }),
    success: function (response) {
      console.log("User email alert state updated:", response);
    },
    error: function (xhr, status, errorThrown) {
      console.error("Error updating email alert state:", status, errorThrown, xhr);
    }
  });
});

function setEmailAlertState(alertId) {
  const emailAlertSwitch = $('#createAlertModal').find('.email-alerts');
  const isChecked = emailAlertSwitch.prop('checked');
  console.log("setEmailAlertState, checked:" + isChecked, alertId);
  $.ajax({
    type: "POST",
    url: "/update_user_email_alert_state",
    contentType: "application/json",
    data: JSON.stringify({
      user_id: alertId,
      email_alerts_enabled: isChecked
    }),
    success: function (response) {
      console.log("User email alert state updated (initial):", response);
    },
    error: function (xhr, status, errorThrown) {
      console.error("Error updating email alert state (initial):", status, errorThrown, xhr);
    }
  });
}