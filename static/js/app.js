console.log("app.js loaded");

$(function () {
    const sessionId = Date.now().toString() + Math.random().toString(36).substring(2);
    const operatorId = 4;
    let isRequestInProgress = false;

    function setLoading(isLoading) {
        $("#send-btn").prop("disabled", isLoading);
        $("#message").prop("disabled", isLoading);
        if (!isLoading) $("#message").focus();
    }

    function scrollBottom() {
        $("#chat-window").scrollTop($("#chat-window")[0].scrollHeight);
    }

    function setStatus(text) {
        if ($("#status").length) $("#status").text(text);
    }

    function actionIcons() {
        return {
            copy: `<svg viewBox="0 0 16 16" fill="none"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M3 10.5V3.5A1.5 1.5 0 0 1 4.5 2h6" stroke="currentColor" stroke-width="1.3"/></svg>`,
            up: `<svg viewBox="0 0 16 16" fill="none"><path d="M6 14H3.5A1.5 1.5 0 0 1 2 12.5V8.9a1.5 1.5 0 0 1 .38-1L6 4V2.5a1 1 0 0 1 1.8-.6L10 4.5V6h2.6a1.5 1.5 0 0 1 1.47 1.78l-.9 4.5A1.5 1.5 0 0 1 11.7 13.5H9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
            down: `<svg viewBox="0 0 16 16" fill="none"><path d="M10 2H12.5A1.5 1.5 0 0 1 14 3.5V7.1a1.5 1.5 0 0 1-.38 1L10 12v1.5a1 1 0 0 1-1.8.6L6 11.5V10H3.4a1.5 1.5 0 0 1-1.47-1.78l.9-4.5A1.5 1.5 0 0 1 4.3 2.5H7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
            regen: `<svg viewBox="0 0 16 16" fill="none"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2v3.6H9.9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>`
        };
    }

    function addUserMessage(message) {
        const icons = actionIcons();
        const $wrap = $(`<div class="msg user"><div class="msg-body"></div></div>`);
        $wrap.find(".msg-body").text(message);

        const $actions = $(`
            <div class="user-actions">
                <button class="act-copy" aria-label="Copy">${icons.copy}</button>
            </div>
        `);
        $wrap.append($actions);

        $actions.find(".act-copy").on("click", function () {
            navigator.clipboard.writeText(message).then(() => {
                const $flash = $(`<span class="copy-flash">Copied</span>`);
                $actions.append($flash).addClass("pinned");
                setTimeout(() => {
                    $flash.remove();
                    $actions.removeClass("pinned");
                }, 1200);
            });
        });

        $("#chat-window").append($wrap);
        scrollBottom();
        return $wrap;
    }

    // insertBefore: optional jQuery element to insert the typing indicator ahead of,
    // so it lands in the same slot as the response it's replacing (regenerate case)
    function showTyping(insertBefore) {
        const $typing = $(`
            <div class="msg ai" id="typing">
                <div class="typing">
                    <div class="thread"><span></span><span></span><span></span></div>
                </div>
            </div>
        `);
        if (insertBefore && insertBefore.length) {
            $typing.insertBefore(insertBefore);
        } else {
            $("#chat-window").append($typing);
        }
        scrollBottom();
    }

    function hideTyping() {
        $("#typing").remove();
    }

    function streamIntoBubble($body, fullText, onDone) {
        const words = fullText.split(/(\s+)/);
        let i = 0;

        function tick() {
            i++;
            const partial = words.slice(0, i).join("");
            $body.html(marked.parse(partial));
            scrollBottom();

            if (i < words.length) {
                const delay = 18 + Math.random() * 35;
                setTimeout(tick, delay);
            } else {
                onDone();
            }
        }
        tick();
    }

    // userMessage: the question this response answers (needed for regenerate)
    // insertBefore: optional jQuery element — reinsert at this position instead of appending
    function addAIMessage(message, userMessage, insertBefore, onStreamComplete) {
        const $wrap = $(`<div class="msg ai"><div class="msg-body"></div></div>`);
        $wrap.data("userMessage", userMessage);

        if (insertBefore && insertBefore.length) {
            $wrap.insertBefore(insertBefore);
        } else {
            $("#chat-window").append($wrap);
        }

        const $body = $wrap.find(".msg-body");
        scrollBottom();

        streamIntoBubble($body, message, () => {
            attachActions($wrap, message);
            if (onStreamComplete) onStreamComplete();
        });
    }

    function attachActions($wrap, rawText) {
        const icons = actionIcons();
        const $actions = $(`
            <div class="msg-actions">
                <button class="act-copy" aria-label="Copy">${icons.copy}</button>
                <button class="act-up" aria-label="Good response">${icons.up}</button>
                <button class="act-down" aria-label="Bad response">${icons.down}</button>
                <button class="act-regen" aria-label="Regenerate">${icons.regen}</button>
            </div>
        `);
        $wrap.append($actions);

        $actions.find(".act-copy").on("click", function () {
            navigator.clipboard.writeText(rawText).then(() => {
                const $flash = $(`<span class="copy-flash">Copied</span>`);
                $actions.append($flash).addClass("pinned");
                setTimeout(() => {
                    $flash.remove();
                    $actions.removeClass("pinned");
                }, 1200);
            });
        });

        $actions.find(".act-up").on("click", function () {
            $(this).toggleClass("active-up");
            $actions.find(".act-down").removeClass("active-down");
        });

        $actions.find(".act-down").on("click", function () {
            $(this).toggleClass("active-down");
            $actions.find(".act-up").removeClass("active-up");
        });

        $actions.find(".act-regen").on("click", function () {
            if (isRequestInProgress) return;
            const userMessage = $wrap.data("userMessage");
            if (!userMessage) return;

            // capture where this bubble currently sits before removing it
            const $anchor = $wrap.next();
            $wrap.remove();
            sendMessage(userMessage, true, $anchor.length ? $anchor : null);
        });

        scrollBottom();
    }

    // insertBefore: passed through only for regenerate, so the new response
    // lands back in its original slot instead of at the bottom of the chat
    function sendMessage(overrideMessage, isRegenerate = false, insertBefore = null) {
        if (isRequestInProgress) return;

        const message = overrideMessage ?? $("#message").val().trim();
        if (message === "") return;

        isRequestInProgress = true;
        setLoading(true);

        if (!isRegenerate) {
            addUserMessage(message);
            $("#message").val("");
        }

        setStatus("Thinking...");
        showTyping(insertBefore);

        function finishTurn() {
            isRequestInProgress = false;
            setLoading(false);
        }

        $.ajax({
            url: "/api/v1/agent/chat",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": "3f1156eabe0f06b216e64852bca1d779213697ffe9c6da536ae0acb8655c6578"
            },
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                operator_id: operatorId,
                session_id: sessionId,
                message: message,
                channel: "chat"
            }),
            success: function (response) {
                hideTyping();
                addAIMessage(response.reply, message, insertBefore, finishTurn);
                if ($("#intent").length) $("#intent").text(response.detected_intent);
                if ($("#escalation").length) {
                    $("#escalation").text(response.requires_escalation ? "Yes" : "No");
                }
                setStatus("Ready");
            },
            error: function (xhr) {
                hideTyping();
                let msg = "Something went wrong reaching the assistant. Please try again.";
                if (xhr.responseJSON?.detail) msg = xhr.responseJSON.detail;
                addAIMessage(msg, message, insertBefore, finishTurn);
                setStatus("Error");
            }
        });
    }

    $("#send-btn").click(() => sendMessage());
    $("#message").keypress(function (e) {
        if (e.which === 13 && !isRequestInProgress) {
            sendMessage();
        }
    });
});
