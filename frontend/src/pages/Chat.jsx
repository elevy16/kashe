import { useState, useEffect, useRef, useCallback } from 'react';
import Navbar from '../components/Navbar';
import './Chat.css';

const CHAT_STORAGE_KEY = 'kashe_chat_history';
const PENDING_LOG_CHALLENGE_KEY = 'kashe_pending_log_challenge';

const GREETING_TIMEOUT_MS = 5000;
const CHAT_REQUEST_TIMEOUT_MS = 85000;

const DEFAULT_WELCOME = {
  id: 0,
  text: "Hi! I'm your Kashé coach. Ask me about your points, challenges, or anything fitness related!",
  sender: 'ai',
};

const KASHE_HELP_FALLBACK_REPLY =
  "I can help you log classes, check your points, enroll in challenges, or redeem rewards. What would you like?";

function readStoredChat() {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const valid = parsed.filter(
      (m) =>
        m &&
        typeof m === 'object' &&
        typeof m.text === 'string' &&
        (m.sender === 'user' || m.sender === 'ai') &&
        !m.isThinking
    );
    return valid.length > 0 ? valid : null;
  } catch {
    return null;
  }
}

function getPendingLogChallenge() {
  try {
    return sessionStorage.getItem(PENDING_LOG_CHALLENGE_KEY) || null;
  } catch {
    return null;
  }
}

function setPendingLogChallenge(title) {
  try {
    if (title && String(title).trim()) {
      sessionStorage.setItem(PENDING_LOG_CHALLENGE_KEY, String(title).trim());
    } else {
      sessionStorage.removeItem(PENDING_LOG_CHALLENGE_KEY);
    }
  } catch {
    // ignore
  }
}

async function fetchPersonalizedGreeting() {
  const token = localStorage.getItem('token');
  const controller = new AbortController();
  const to = setTimeout(() => controller.abort(), GREETING_TIMEOUT_MS);
  try {
    const response = await fetch('http://127.0.0.1:5000/api/chat/greeting', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok || !data.greeting) {
      throw new Error(data.error || 'greeting failed');
    }
    return data.greeting;
  } finally {
    clearTimeout(to);
  }
}

function isAffirmativeForPending(text) {
  const t = text.trim().toLowerCase();
  if (!t || t.length > 80) return false;
  return /^(yes+|y+|yep+|yeah+|sure+|ok+|okay+|please\b|do it|absolutely|sounds?\s+good|go\s+ahead|\bfine\b|let'?s\s+do\s+it)([\s!.?,]|$)/i.test(
    t
  );
}

function Chat({ setIsAuthenticated }) {
  const [messages, setMessages] = useState(() => readStoredChat() ?? null);
  const [greetingLoading, setGreetingLoading] = useState(() => !readStoredChat());
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [inputHint, setInputHint] = useState('');
  const messagesEndRef = useRef(null);
  /** Bumps on each greeting fetch so overlapping requests cannot overwrite a newer run. */
  const greetingFetchGenRef = useRef(0);

  const loadFreshGreeting = useCallback(async () => {
    const gen = ++greetingFetchGenRef.current;
    setGreetingLoading(true);
    setMessages(null);
    try {
      const text = await fetchPersonalizedGreeting();
      if (gen !== greetingFetchGenRef.current) return;
      setMessages([{ id: 0, text: String(text).trim(), sender: 'ai' }]);
    } catch {
      if (gen !== greetingFetchGenRef.current) return;
      setMessages([DEFAULT_WELCOME]);
    } finally {
      if (gen === greetingFetchGenRef.current) {
        setGreetingLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (readStoredChat()) {
      return;
    }
    loadFreshGreeting();
  }, [loadFreshGreeting]);

  useEffect(() => {
    if (!messages || greetingLoading) return;
    const persistable = messages.filter((m) => !m.isThinking);
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persistable));
    } catch {
      // sessionStorage unavailable or quota exceeded
    }
  }, [messages, greetingLoading]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, greetingLoading]);

  const handleNewChat = () => {
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      // ignore
    }
    setPendingLogChallenge(null);
    void loadFreshGreeting();
  };

  useEffect(() => {
    if (inputValue.trim()) setInputHint('');
  }, [inputValue]);

  const sendMessage = async () => {
    const trimmed = inputValue.trim();
    if (!trimmed || !messages) {
      setInputHint('Type a question or ask me anything about your Kashé challenges and points.');
      return;
    }

    const affirm = isAffirmativeForPending(trimmed);
    let pendingChallengeTitle = affirm ? getPendingLogChallenge() : null;
    if (!affirm) {
      setPendingLogChallenge(null);
    }

    setMessages((prev) => {
      const maxId = prev.reduce(
        (m, x) => (typeof x.id === 'number' && x.id > m ? x.id : m),
        -1
      );
      const userId = maxId + 1;
      const thinkingId = maxId + 2;
      return [
        ...prev,
        { id: userId, text: trimmed, sender: 'user' },
        { id: thinkingId, text: 'thinking...', sender: 'ai', isThinking: true },
      ];
    });
    setInputValue('');
    setInputHint('');
    setLoading(true);

    const history = messages
      .filter((m) => !m.isThinking)
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'model',
        text: m.text,
      }));

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CHAT_REQUEST_TIMEOUT_MS);

    try {
      const token = localStorage.getItem('token');
      const body = {
        message: trimmed,
        history,
        ...(pendingChallengeTitle ? { pending_challenge_title: pendingChallengeTitle } : {}),
      };

      let response = await fetch('http://127.0.0.1:5000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      let data;
      try {
        data = await response.json();
      } catch {
        data = {};
      }

      if (!response.ok) {
        const errText =
          data.error ||
          `Something went wrong (${response.status}). ${KASHE_HELP_FALLBACK_REPLY}`;
        throw new Error(errText);
      }

      let replyText =
        typeof data.reply === 'string'
          ? data.reply.trim()
          : '';
      if (
        replyText.includes("didn't understand") ||
        replyText.includes('did not understand') ||
        !replyText
      ) {
        replyText = replyText.replace(/sorry[^.]*\.?\s*/gi, '').trim() || '';
        replyText =
          replyText || data.error?.trim?.() || KASHE_HELP_FALLBACK_REPLY;
      }

      const nextPending =
        typeof data.pending_challenge_title === 'string'
          ? data.pending_challenge_title.trim()
          : data.pending_challenge_title;
      if (nextPending) {
        setPendingLogChallenge(nextPending);
      } else {
        setPendingLogChallenge(null);
      }

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (!last?.isThinking) return prev;
        updated[updated.length - 1] = {
          ...last,
          text: replyText,
          isThinking: false,
        };
        return updated;
      });
    } catch (err) {
      const abort = err?.name === 'AbortError';
      const text = abort
        ? 'That request took longer than usual. Kashé might be busy — try logging a class by challenge name or check your Challenges tab.'
        : (err.message && String(err.message).trim()) ||
          'Connection issue. Double-check your network and try again.';

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (!last?.isThinking) return prev;
        updated[updated.length - 1] = {
          ...last,
          text: `${text}\n\n${KASHE_HELP_FALLBACK_REPLY}`,
          isThinking: false,
        };
        return updated;
      });
    } finally {
      clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const showGreetingPlaceholder = greetingLoading && (!messages || messages.length === 0);

  return (
    <div className="chat-container">
      <div className="chat-header">
        <button
          type="button"
          className="chat-new-btn"
          onClick={handleNewChat}
          disabled={greetingLoading}
        >
          New chat
        </button>
      </div>

      <div className="messages-area">
        {showGreetingPlaceholder && (
          <div className="greeting-loading">Getting your update...</div>
        )}
        {!showGreetingPlaceholder &&
          messages &&
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-bubble ${msg.sender} ${
                msg.isThinking ? 'thinking' : ''
              }`}
            >
              {msg.text}
            </div>
          ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <div className="chat-input-stack">
          {inputHint && <p className="chat-input-hint">{inputHint}</p>}
          <div className="chat-input-row">
            <input
              type="text"
              className="message-input"
              placeholder="Ask me anything..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={loading || greetingLoading || !messages}
            />
            <button
              type="button"
              className="send-button"
              onClick={sendMessage}
              disabled={loading || greetingLoading || !messages || !inputValue.trim()}
            >
              Send
            </button>
          </div>
        </div>
      </div>

      <Navbar setIsAuthenticated={setIsAuthenticated} />
    </div>
  );
}

export default Chat;
