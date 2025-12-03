function saveFeedback() {
    let name = document.getElementById("name").value;
    let feedback = document.getElementById("feedback").value;

    fetch("/save-feedback", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, feedback})
    })
    .then(res => res.json())
    .then(data => {
        alert("Feedback saved!");
    });
}
