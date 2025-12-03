function sendMessage() {
    let text = document.getElementById("userInput").value;

    fetch(`/get?msg=${text}`)
    .then(response => response.json())
    .then(data => {
        document.getElementById("reply").innerText = data.reply;
    });
}
