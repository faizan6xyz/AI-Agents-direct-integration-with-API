async function getUserDetails() {
    const token = localStorage.getItem("authToken"); 
    if (!token){
        return false}
    try {
    const response = await fetch("backend_user_check_url", {
      method: "GET", // or POST if you're sending a body too
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      }});
    if (!response.ok) {
      if (response.status === 401) {
        console.error("Token invalid or expired");
      }
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    if (data.status){
        return true }}   
     catch (err) {
    console.error("Request failed:", err);
  }
}

