// JavaScript Document - alert-filter.js
function filterAlertsByDate(alerts, selectedDate) {
    if (!alerts || alerts.length === 0) {
        return [];
    }

    // Ensure selectedDate is a valid Date Object
    const selectedDateObj = new Date(selectedDate);
    selectedDateObj.setHours(0, 0, 0, 0); // Set to start of day for comparison

    return alerts.filter(alert => {
        const alertStart = new Date(alert.start * 1000); // Convert UNIX timestamp to Date
        const alertEnd = new Date(alert.end * 1000); // Convert UNIX timestamp to Date
		
		//Set to start of the day, to be sure.
		const alertStartDay = new Date(alertStart);
		alertStartDay.setHours(0,0,0,0);
		const alertEndDay = new Date(alertEnd);
		alertEndDay.setHours(0,0,0,0);

        // Check if the selectedDate falls within the range of the alert's start and end dates
        return selectedDateObj >= alertStartDay && selectedDateObj <= alertEndDay;
    });
}

function clearAlertsFromMap() {
    // Clear existing incident alert layers only
     map.eachLayer(function (layer) {
       if (layer instanceof L.GeoJSON && layer.options && layer.options.onEachFeature && !layer.alertZone) {
        map.removeLayer(layer);
       }
     });
      // Close any open popups
      map.closePopup();

}


// Add an event listener to the document that listens for carousel date selection
document.addEventListener('carouselDateSelected', function (e) {
    const selectedDate = e.detail.selectedDate;
	let filteredAlerts = [];

    if (selectedDate) {
        clearAlertsFromMap();
        
        if (selectedDate === new Date().toISOString().split('T')[0] || selectedDate === 'today') {
            console.log("Showing all alerts");
            filteredAlerts = alerts;
        } else {
            console.log("Filtering alerts by date:", selectedDate);
            filteredAlerts = filterAlertsByDate(alerts, selectedDate);
        }
        displayAlerts(filteredAlerts);
    }
	// Update severity counts on HTML
let severityCounts = extractSeverityCounts(filteredAlerts);
document.getElementById('minor-alerts').textContent = severityCounts.minor;
document.getElementById('moderate-alerts').textContent = severityCounts.moderate;
document.getElementById('severe-alerts').textContent = severityCounts.severe;
document.getElementById('extreme-alerts').textContent = severityCounts.extreme;
document.getElementById('unknown-alerts').textContent = severityCounts.unknown;
});



function extractSeverityCounts(alerts) {
    let severityCounts = {
        minor: 0,
		moderate: 0,
        severe: 0,
        extreme: 0,
		unknown: 0
    }
    
    alerts.forEach(alert => {
        if (alert.severity === 'Minor') {
            severityCounts.minor++;
        }
        else if (alert.severity === 'Moderate') {
            severityCounts.moderate++;
		}
        else if (alert.severity === 'Severe') {
            severityCounts.severe++;
        }
        else if (alert.severity === 'Extreme') {
            severityCounts.extreme++;
        }
		else if (alert.severity === 'Unknown') {
            severityCounts.unknown++;
        }
    });

    return severityCounts;
}

