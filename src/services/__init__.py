"""Business-logic services for EmailPOC.

The service layer sits between the HTTP routes (:mod:`src.route`) and the
infrastructure (:mod:`src.db`, the email providers and the webhook
parsers). Routes stay thin — they parse the request and delegate to a
service method — while all orchestration lives here.

- :mod:`src.services.conversation_service` defines
  :class:`ConversationService`, which creates conversations, sends RFQ
  emails and processes inbound replies.
"""

from src.services.conversation_service import ConversationService

__all__ = ["ConversationService"]
