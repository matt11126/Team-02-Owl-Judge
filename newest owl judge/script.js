document.addEventListener("DOMContentLoaded", function() {
    createBubbles();
});

function toggleMenu() {
    // Add function for hamburger menu if needed
}

function showVotingSection() {
    const selectedProject = document.getElementById("projectDropdown").value;
    const votingSection = document.getElementById("votingSection");
    
    if (selectedProject) {
        votingSection.classList.remove("hidden");
    } else {
        votingSection.classList.add("hidden");
    }
}

// Create bubbles for each rating category
function createBubbles() {
    const categories = document.querySelectorAll(".rating-category .rating-bubbles");

    categories.forEach(category => {
        for (let i = 0; i <= 10; i++) {
            let bubble = document.createElement("div");
            bubble.classList.add("bubble");
            bubble.innerText = i;
            bubble.dataset.value = i;

            bubble.addEventListener("click", function() {
                selectBubble(category, bubble);
            });

            category.appendChild(bubble);
        }
    });
}

// Highlight the selected bubble
function selectBubble(category, selectedBubble) {
    let bubbles = category.children;
    for (let bubble of bubbles) {
        bubble.classList.remove("selected");
    }
    selectedBubble.classList.add("selected");
}

// Calculate the average score
function calculateScore() {
    let totalScore = 0;
    let numCategories = 0;
    
    document.querySelectorAll(".rating-category .rating-bubbles").forEach(category => {
        let selectedBubble = category.querySelector(".bubble.selected");
        if (selectedBubble) {
            totalScore += parseInt(selectedBubble.dataset.value);
            numCategories++;
        }
    });

    let averageScore = numCategories > 0 ? (totalScore / numCategories) * 10 : 0;
    document.getElementById("finalScore").innerText = Math.round(averageScore);
}
