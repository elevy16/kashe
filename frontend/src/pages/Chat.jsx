import { useState, useEffect, useRef } from 'react';
import Navbar from '../components/Navbar';
import './Chat.css';

const CHAT_STORAGE_KEY = 'kashe_chat_history';

const DEFAULT_WELCOME = {
  id: 0,
  text: "Hi! I'm your Kashé coach. Ask me about your points, challenges, or anything fitness related!",
  sender: 'ai',
};

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

function Chat() {
  const [messages, setMessages] = useState(() => readStoredChat() ?? [DEFAULT_WELCOME]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    const persistable = messages.filter((m) => !m.isThinking);
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persistable));
    } catch {
      // sessionStorage unavailable or quota exceeded
    }
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    const trimmed = inputValue.trim();
    if (!trimmed) return;

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
    setLoading(true);

    const history = messages
      .filter((m) => !m.isThinking)
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'model',
        text: m.text,
      }));

    try {
      const token = localStorage.getItem('token');
      const response = await fetch('http://127.0.0.1:5000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: trimmed, history }),
      });

      if (!response.ok) {
        throw new Error('Failed to get response');
      }

      const data = await response.json();

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (!last?.isThinking) return prev;
        updated[updated.length - 1] = {
          ...last,
          text:
            data.reply ||
            "I'm sorry, I didn't understand that. Please try again.",
          isThinking: false,
        };
        return updated;
      });
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (!last?.isThinking) return prev;
        updated[updated.length - 1] = {
          ...last,
          text: 'Sorry, I encountered an error. Please try again.',
          isThinking: false,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="chat-container">
      <div className="messages-area">
        {messages.map((msg) => (
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
        <input
          type="text"
          className="message-input"
          placeholder="Ask me anything..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          disabled={loading}
        />
        <button
          className="send-button"
          onClick={sendMessage}
          disabled={loading || !inputValue.trim()}
        >
          Send
        </button>
      </div>

      <Navbar />
    </div>
  );
}

export default Chat;
