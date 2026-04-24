document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const triesCount = document.getElementById('tries-count');
    const triesBar = document.getElementById('tries-bar');
    const lastTopicPill = document.getElementById('last-topic');
    const resetBtn = document.getElementById('reset-btn');
    const attemptsCircle = document.getElementById('attempts-circle');
    const maxTries = 5;

    // Initialize state
    fetchState();
    startClock();

    function startClock() {
        updateClock();
        setInterval(updateClock, 1000);
    }

    function updateClock() {
        const now = new Date();
        const timeEl = document.getElementById('clock-time');
        const dateEl = document.getElementById('clock-date');
        const greetingEl = document.getElementById('greeting-text');

        if (timeEl) {
            timeEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        if (dateEl) {
            dateEl.textContent = now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
        }
        if (greetingEl) {
            const hour = now.getHours();
            if (hour < 12) greetingEl.textContent = "Good Morning,";
            else if (hour < 18) greetingEl.textContent = "Good Afternoon,";
            else greetingEl.textContent = "Good Evening,";
        }
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            try {
                const response = await fetch('/api/reset', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    updateTriesUI(data.tries_left);
                    addSystemAlert("Tries have been reset to 5.", "correct");
                    userInput.disabled = false;
                    sendBtn.disabled = false;
                    userInput.placeholder = "Ask a question or answer the tutor...";
                }
            } catch (error) {
                console.error("Failed to reset tries:", error);
                addSystemAlert("Failed to reset tries.", "incorrect");
            }
        });
    }

    async function fetchState() {
        try {
            const response = await fetch('/api/state');
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            const data = await response.json();
            
            updateTriesUI(data.tries_left);
            if (data.last_concept) {
                lastTopicPill.textContent = data.last_concept;
            }

            // Remove loading indicator
            const initialLoading = document.querySelector('.initial-loading');
            if (initialLoading) initialLoading.remove();

            if (data.history && data.history.length > 0) {
                data.history.forEach(msg => {
                    addMessage(msg.message, msg.sender);
                });
            }

            if (data.initial_message) {
                addMessage(data.initial_message, 'tutor');
            } else if (!data.history || data.history.length === 0) {
                addMessage("Welcome! What topic would you like to explore today?", 'tutor');
            }

        } catch (error) {
            console.error("Failed to fetch state:", error);
            addSystemAlert("Error connecting to the server.", "incorrect");
        }
    }

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = userInput.value.trim();
        if (!text) return;

        // Check if out of tries locally before sending
        if (parseInt(triesCount.textContent) <= 0) {
            addSystemAlert("You are out of tries! Refresh to restart (if backend allows).", "incorrect");
            return;
        }

        // Add user message
        addMessage(text, 'user');
        userInput.value = '';
        
        // Disable input
        setLoadingState(true);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });

            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }

            const data = await response.json();

            if (data.error) {
                addSystemAlert(data.error, "incorrect");
            } else {
                handleTutorResponse(data);
            }
        } catch (error) {
            console.error("Chat error:", error);
            addSystemAlert("Failed to send message.", "incorrect");
        } finally {
            setLoadingState(false);
        }
    });

    function handleTutorResponse(data) {
        // Handle correctness
        if (data.is_correct) {
            addSystemAlert("Correct answer! Unlocking response...", "correct");
        } else if (data.deduct_try) {
            addSystemAlert("Incorrect. Deducting a try.", "incorrect");
            triggerShakeEffect();
        }

        // Update tries if changed
        if (data.tries_left !== undefined) {
            updateTriesUI(data.tries_left);
        }

        // Update concept if new one learned
        if (data.new_concept_learned) {
            lastTopicPill.textContent = data.new_concept_learned;
            lastTopicPill.style.animation = 'pulse 1s';
            setTimeout(() => lastTopicPill.style.animation = '', 1000);
            addSystemAlert(`Mastered: ${data.new_concept_learned}`, "correct");
        }

        // Display tutor reply
        addMessage(data.tutor_reply, 'tutor');
    }

    function addMessage(text, sender) {
        const div = document.createElement('div');
        div.className = `message ${sender}-message`;
        
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble glass';
        
        // Convert newlines to br for simple formatting
        bubble.innerHTML = text.replace(/\n/g, '<br>');
        
        div.appendChild(bubble);
        chatMessages.appendChild(div);
        scrollToBottom();
    }

    function addSystemAlert(text, type) {
        const div = document.createElement('div');
        div.className = `system-alert ${type}`;
        div.textContent = text;
        chatMessages.appendChild(div);
        scrollToBottom();
    }

    function addTypingIndicator() {
        const div = document.createElement('div');
        div.className = `message tutor-message typing-container`;
        div.id = 'current-typing-indicator';
        
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble glass';
        bubble.innerHTML = `
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        `;
        
        div.appendChild(bubble);
        chatMessages.appendChild(div);
        scrollToBottom();
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('current-typing-indicator');
        if (indicator) indicator.remove();
    }

    function setLoadingState(isLoading) {
        userInput.disabled = isLoading;
        sendBtn.disabled = isLoading;
        if (isLoading) {
            addTypingIndicator();
        } else {
            removeTypingIndicator();
            userInput.focus();
        }
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function updateTriesUI(tries) {
        // Animate counter
        const oldTries = parseInt(triesCount.textContent);
        if (oldTries !== tries) {
            triesCount.textContent = tries;
            triesCount.style.transform = 'scale(1.5)';
            setTimeout(() => triesCount.style.transform = 'scale(1)', 200);
        }

        // Update radial progress
        if (attemptsCircle) {
            const radius = attemptsCircle.r.baseVal.value;
            const circumference = radius * 2 * Math.PI;
            const percentage = Math.max(0, tries / maxTries);
            const offset = circumference - (percentage * circumference);
            attemptsCircle.style.strokeDashoffset = offset;
            
            if (tries <= 2) {
                attemptsCircle.style.stroke = 'var(--danger)';
                triesCount.style.color = 'var(--danger)';
            } else {
                attemptsCircle.style.stroke = 'var(--primary)';
                triesCount.style.color = '';
            }
        }

        if (tries <= 0) {
            userInput.disabled = true;
            userInput.placeholder = "Out of tries. Restart server.";
            sendBtn.disabled = true;
        }
    }

    function triggerShakeEffect() {
        const statsCard = document.querySelector('.stats-card');
        statsCard.classList.add('shake');
        setTimeout(() => statsCard.classList.remove('shake'), 500);
    }
});
