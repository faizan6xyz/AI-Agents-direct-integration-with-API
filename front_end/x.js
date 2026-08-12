// Bar Chart
const barCtx = document.getElementById("barChart").getContext("2d");
new Chart(barCtx, {
  type: "bar",
  data: {
    labels: ["Jan", "Feb", "Mar", "Apr", "May"],
    datasets: [{
      label: "Followers Gained",
      data: [120, 190, 300, 250, 400],
      backgroundColor: "rgba(54, 162, 235, 0.6)",
      borderColor: "rgba(54, 162, 235, 1)",
      borderWidth: 1
    }]
  },
  options: {
    responsive: true,
    scales: {
      y: { beginAtZero: true }
    }
  }
});

// Pie Chart
const pieCtx = document.getElementById("pieChart").getContext("2d");
new Chart(pieCtx, {
  type: "pie",
  data: {
    labels: ["Instagram", "WhatsApp", "Gmail"],
    datasets: [{
      label: "Conversion Source",
      data: [45, 30, 25],
      backgroundColor: [
        "rgba(255, 99, 132, 0.7)",
        "rgba(75, 192, 192, 0.7)",
        "rgba(255, 206, 86, 0.7)"
      ]
    }]
  },
  options: {
    responsive: true
  }
}); 