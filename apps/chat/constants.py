"""Chat system message copy (English — shown in mobile UI)."""

SAFETY_WELCOME_TEXT = (
    'For your safety, we recommend keeping all communication and payments within AutoHandy. '
    'AutoHandy cannot guarantee payment protection, dispute resolution, or service quality '
    'for arrangements made outside the platform.'
)

CONTACT_WARNING_TEXT = (
    'Warning: AutoHandy is not responsible for payments, services, disputes, or agreements '
    'arranged outside the platform. For your protection, we recommend communicating and '
    'completing payments through AutoHandy.'
)

CONVERSATION_CLOSED_TEXT = (
    'Conversation closed. If you need further assistance, please contact AutoHandy Support.'
)

MASTER_GREETING_TEXT_TEMPLATE = (
    "Hi! I'm {name}, your master for this order. "
    "Feel free to message me here if you have any questions."
)
MASTER_GREETING_TEXT_FALLBACK = (
    'Hi! I\'m your master for this order. '
    'Feel free to message me here if you have any questions.'
)

SYSTEM_CODE_SAFETY_WELCOME = 'safety_welcome'
SYSTEM_CODE_CONTACT_WARNING = 'contact_warning'
SYSTEM_CODE_CONVERSATION_CLOSED = 'conversation_closed'
SYSTEM_CODE_MASTER_GREETING = 'master_greeting'

MESSAGING_CLOSED_ERROR = (
    'This conversation is closed. You can still read the history, but new messages cannot be sent.'
)
