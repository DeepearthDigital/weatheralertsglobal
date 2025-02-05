const carouselItems = document.querySelectorAll('.date-carousel-item');
const todayCarouselItem = document.getElementById('today-carousel-item');

let startX;
let scrollLeft;
let isDown = false;

const slider = document.querySelector('.date-carousel');

slider.addEventListener('mousedown', (e) => {
  isDown = true;
  slider.classList.add('active');
  startX = e.pageX - slider.offsetLeft;
  scrollLeft = slider.scrollLeft;
});

slider.addEventListener('mouseleave', () => {
  isDown = false;
  slider.classList.remove('active');
});

slider.addEventListener('mouseup', () => {
  isDown = false;
  slider.classList.remove('active');
});

slider.addEventListener('mousemove', (e) => {
  if (!isDown) return; // stop the function from running
  e.preventDefault();
  const x = e.pageX - slider.offsetLeft;
  const walk = (x - startX) * 3; // scroll-fast
  slider.scrollLeft = scrollLeft - walk;
});

// Function to format a date object as "Day Date Month"
function formatDate(date) {
  const day = date.toLocaleDateString('en-US', {
    weekday: 'short'
  });
  const dayOfMonth = date.getDate();
  const month = date.toLocaleDateString('en-US', {
    month: 'short'
  });
  return `${day} ${dayOfMonth} ${month}`;
}

// Get today's date
const today = new Date();
const formattedToday = formatDate(today);

// Update the 4th box with today's date
if (todayCarouselItem) {
  todayCarouselItem.querySelector('h3').textContent = formattedToday;
}

// Calculate and set the dates for other carousel items
const days = [-3, -2, -1, 0, 1, 2, 3];
carouselItems.forEach((item, index) => {
  const dayOffset = days[index];
  const date = new Date(today);
  date.setDate(today.getDate() + dayOffset);

  if (item !== todayCarouselItem) { // Skip the today's box we've already done
    const formattedDate = formatDate(date);
    item.querySelector('h3').textContent = formattedDate;
    item.setAttribute('data-date', date.toISOString().split('T')[0]) // use date in "YYYY-MM-DD"
  }
});

function updateCarouselCounts(alerts) {
  const carouselItems = document.querySelectorAll('.date-carousel-item');
  carouselItems.forEach(item => {
    const date = item.getAttribute('data-date');
    let filteredAlerts = [];

    if (date === 'today') {
      filteredAlerts = alerts
    } else {
      filteredAlerts = filterAlertsByDate(alerts, date);
    }

    const count = filteredAlerts.length;
    item.querySelector('p').textContent = `${count} Alert${count !== 1 ? 's' : ''}`;
  });
}

// Add an event listener to the document that listens for carousel date selection
document.addEventListener('carouselDateSelected', function (e) {
  const selectedDate = e.detail.selectedDate;

  if (selectedDate) {
    clearAlertsFromMap();

    let filteredAlerts = [];
    if (selectedDate === new Date().toISOString().split('T')[0] || selectedDate === 'today') {
      console.log("Showing all alerts");
      filteredAlerts = alerts;
    } else {
      console.log("Filtering alerts by date:", selectedDate);
      filteredAlerts = filterAlertsByDate(alerts, selectedDate);
    }
    displayAlerts(filteredAlerts);
  }
});

// Call this function after alerts are loaded or updated
function handleNewAlertData(alerts) {
  updateCarouselCounts(alerts);
}

//Carousel and info panel buttons states for moving the menu up and down
carouselItems.forEach(carouselItem => {
  carouselItem.addEventListener('click', () => {
    carouselItems.forEach(i => i.classList.remove('active'));
    carouselItems.forEach(i => i.classList.remove('hover'));

    // Get menu and date carousel container
    const infoMenu = document.querySelector('.info-menu-container');
    const dateCarousel = document.querySelector('.date-carousel-container');

    // Show it (slide up) if not active yet
    infoMenu.classList.add('active');
    dateCarousel.classList.add('active');

    // Save clicked item index to localStorage
    let carouselIndex = [...carouselItems].indexOf(carouselItem);
    localStorage.setItem("activeCarouselIndex", carouselIndex);

    carouselItem.classList.add('active');

    // Get the selected date from the clicked item
    const selectedDate = carouselItem.getAttribute('data-date');
    console.log("Selected Date: " + selectedDate);

    // Dispatch custom event with the selected date
    const event = new CustomEvent('carouselDateSelected', {
      detail: {
        selectedDate: selectedDate
      }
    });
    document.dispatchEvent(event);
  });
});

// Load active item from localStorage when page loads
window.onload = function () {
  let activeCarouselIndex = localStorage.getItem("activeCarouselIndex");
  if (activeCarouselIndex) {
    carouselItems[activeCarouselIndex].click();
  }

  const infoMenu = document.querySelector('.info-menu-container');
  const dateCarousel = document.querySelector('.date-carousel-container');

  infoMenu.classList.remove('active');
  dateCarousel.classList.remove('active');
}


carouselItems.forEach(carouselItem => {
  carouselItem.addEventListener('mouseover', () => {
    carouselItems.forEach(i => i.classList.remove('hover'));
    carouselItem.classList.add('hover');
  });
});

let severitySquares = document.querySelectorAll('.severity-square');
severitySquares.forEach(severitySquare => {
  // Mouseover event
  severitySquare.addEventListener('mouseover', () => {
    severitySquares.forEach(i => i.classList.remove('hover'));
    severitySquare.classList.add('hover');
  });

  // Click event
  severitySquare.addEventListener('click', () => {
    if (severitySquare.classList.contains('active')) {
      severitySquare.classList.remove('active');
    } else {
      // remove toggled class from all other severity squares
      severitySquares.forEach(i => i.classList.remove('active'));
      // add toggled class to the clicked severity square
      severitySquare.classList.add('active');
    }
  });
});


//MapID and button state interactivity
const buttonContainer = document.querySelector('.date-carousel');
console.log("buttonContainer:", buttonContainer); // Log the selected element
let isInteracting = false;

buttonContainer.addEventListener('mouseover', function () {
  isInteracting = true;
  buttonContainer.classList.add('interactive');
});

buttonContainer.addEventListener('mousedown', function () {
  isInteracting = true;
  buttonContainer.classList.add('interactive');
});

buttonContainer.addEventListener('mouseup', function () {
  isInteracting = false;
  setTimeout(() => {
    if (!isInteracting) {
      buttonContainer.classList.remove('interactive');
    }
  }, 100);
});

buttonContainer.addEventListener('mouseleave', function () {
  isInteracting = false;
  setTimeout(() => {
    if (!isInteracting) {
      buttonContainer.classList.remove('interactive');
    }
  }, 100);
});
document.addEventListener('click', function (e) {
  const infoMenu = document.querySelector('.info-menu-container');
  const dateCarousel = document.querySelector('.date-carousel-container');

  const clickedInsideInfoMenu = infoMenu.contains(e.target);
  const clickedInsideDateCarousel = dateCarousel.contains(e.target);
  
  if (!clickedInsideInfoMenu && !clickedInsideDateCarousel) {
      // Click was outside of both elements, so hide them
      infoMenu.classList.remove('active');
      dateCarousel.classList.remove('active');
  }
});

const dateCarousel = document.querySelector('.date-carousel-container');
dateCarousel.addEventListener('mouseleave', function (e) {
    // Remove active/hover state from all carousel items
    const carouselItems = dateCarousel.querySelectorAll('.date-carousel-item');
    carouselItems.forEach(i => i.classList.remove('active', 'hover'));
	    // Access the locally stored state
    let activeCarouselIndex = localStorage.getItem("activeCarouselIndex");
    
    // If an index exists in local storage, apply 'active' class to that carousel item
    if(activeCarouselIndex) {
        carouselItems[activeCarouselIndex].classList.add('active');
    }
});