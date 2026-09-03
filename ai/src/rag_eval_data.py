"""
Labeled test cases for evaluating RETRIEVAL quality specifically —
distinct from classifier accuracy. Each case specifies a complaint,
its correct department, and a keyword/phrase that MUST appear
somewhere in the retrieved chunks for retrieval to be considered correct.
"""

RAG_TEST_CASES = [
    {
        "text": "my order hasn't arrived in 3 weeks, order ORD-1234",
        "department": "logistics",
        "expected_keyword": "14 business days",
    },
    {
        "text": "I was charged twice for my subscription this month",
        "department": "billing",
        "expected_keyword": "duplicate charge",
    },
    {
        "text": "I can't log into my account, getting error E-402",
        "department": "tech_support",
        "expected_keyword": "password reset",
    },
    {
        "text": "I need my account deleted, this is a GDPR request",
        "department": "customer_service",
        "expected_keyword": "GDPR",
    },
    {
        "text": "why is my invoice showing $49.99 when I signed up for $29.99",
        "department": "billing",
        "expected_keyword": "signup record",
    },
    {
        "text": "someone else logged into my account and changed my password",
        "department": "tech_support",
        "expected_keyword": "account takeover",
    },
    {
        "text": "can I change my delivery address after ordering?",
        "department": "logistics",
        "expected_keyword": "shipped",
    },
    {
        "text": "my item arrived damaged, what do I do?",
        "department": "logistics",
        "expected_keyword": "48 hours",
    },
    {
        "text": "app keeps crashing when I open settings",
        "department": "tech_support",
        "expected_keyword": "crash",
    },
    {
        "text": "a promo code didn't apply at checkout",
        "department": "billing",
        "expected_keyword": "promotional",
    },
]