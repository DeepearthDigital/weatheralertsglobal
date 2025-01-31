document.addEventListener('DOMContentLoaded', function () {
  const mobileNav = document.querySelector('.mobile-nav');

  if (window.innerWidth > 768) {
    if (!mobileNav.classList.contains('open')) {
      mobileNav.classList.add('open');
    }
  }

  const buttons = document.querySelectorAll('.top-right-button-set button');
  const statsButtonToggle = document.querySelector('.top-right-button-set .icon-button-stats-toggle');
  const showHideAlertZonesToggle = document.querySelector('.top-right-button-set .icon-button-show-hide-alert-zones-toggle');
  const showHideAlertZonesIcon = showHideAlertZonesToggle.querySelector('i');

  statsButtonToggle.addEventListener('click', () => {
    mobileNav.classList.toggle('open');
  });

  if (statsButtonToggle) {
    statsButtonToggle.classList.add('active');
  }

  if (showHideAlertZonesToggle) {
    showHideAlertZonesToggle.classList.add('active');
  }
	
    // Set initial state of show/hide icon
    if (showHideAlertZonesToggle) {
        showHideAlertZonesToggle.classList.add('active');
        showHideAlertZonesIcon.classList.remove('fa-eye-slash');
        showHideAlertZonesIcon.classList.add('fa-eye');
        showHideAlertZonesIcon.classList.add('fa-solid')

  }

  buttons.forEach(button => {
    button.addEventListener('click', function () {
      this.classList.toggle('active');
      // Add functionality here on button toggle
      // Example:
      if (this.id === 'showAlertsButton') {
        toggleAlertVisibility(showHideAlertZonesIcon);
      } else if (this.id === 'createAlertButton') {
        startDraw();
      } else if (this.id === 'deleteAllAlertsButton') {
        clearAllAlerts();
      }else if (this.id === 'drawPolygonButton'){
        startPolygonDraw();
	  }else if (this.id === 'drawRectangleButton'){
        startRectangleDraw();
      }  else if (this.classList.contains('icon-button-stats-toggle')) {
        // Example code for stat button
      }
    });
  });

function startRectangleDraw() {
  console.log("startRectangleDraw()");
  rectangleDrawer = new L.Draw.Rectangle(map);
  currentDrawer = rectangleDrawer; // update currentDrawer
  rectangleDrawer.enable();
    map.on(L.Draw.Event.CREATED, function (e) {
        let type = e.layerType;
        let layer = e.layer;
        
        if (type === 'rectangle') {
          drawnItems.addLayer(layer);
          console.log("Finished rectangle draw", layer.getLatLngs());
          rectangleDrawer.disable();
          map.off(L.Draw.Event.CREATED)
      }
    });
}
	

function startPolygonDraw() {
  console.log("startPolygonDraw()");
  polygonDrawer = new L.Draw.Polygon(map);
  currentDrawer = polygonDrawer; // update currentDrawer
  polygonDrawer.enable();
    map.on(L.Draw.Event.CREATED, function (e) {
        let type = e.layerType;
        let layer = e.layer;
        
        if (type === 'polygon') {
          drawnItems.addLayer(layer);
          console.log("Finished polygon draw", layer.getLatLngs());
          polygonDrawer.disable();
          map.off(L.Draw.Event.CREATED)
      }
    });
}
		
  // Function to make alerts visible or invisible
  function toggleAlertVisibility(icon) {
    const showAlertsButton = document.getElementById('showAlertsButton');
    if (showAlertsButton.classList.contains('active')) {
      // Show eye icon
      icon.classList.remove('fa-eye-slash');
      icon.classList.add('fa-eye');
      icon.classList.add('fa-solid')
      // Hide alerts
      console.log("Hiding alerts");
    } else {
      // show eye-slash icon
      icon.classList.remove('fa-eye');
      icon.classList.add('fa-eye-slash');
      icon.classList.add('fa-solid')
      // show alerts
      console.log("Showing alerts");
    }
  }

  function clearAllAlerts() {
    //Clear all alerts
    console.log("Clear all alerts");
  }

  function startDraw() {
    console.log("startDraw()");
  }
});

