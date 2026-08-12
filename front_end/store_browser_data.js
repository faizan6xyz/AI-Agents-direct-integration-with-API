const data = { name: "Faizan", role: "AI/ML Engineer", project: "MessageFlow" };

function addData() {
    const container = document.createElement("div");
    container.id = "data-container";
    container.innerText = JSON.stringify(data, null, 2);
    document.body.appendChild(container);
    console.log("Data added to DOM:", data);}

function printData() {
    const container = document.getElementById("data-container");
    if (container) {
        console.log("Current data on page:", container.innerText);}
    else {
        console.log("No data found in DOM.");}}

function removeData() {
    const container = document.getElementById("data-container");
    if (container) {
        container.remove();
        console.log("Data removed from DOM.");}
    else {
        console.log("Nothing to remove.");    }}

addData();
// setTimeout(() => { printData();}, 1000);   // write the data after the 1 second of loading  
// setTimeout(() => {removeData();}, 2000);  // remvoes the data after the 1 second of loading 