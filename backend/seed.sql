-- Sample data — mirrors the walkthrough example from the design doc

INSERT INTO users (name, email, password_hash, role) VALUES
    ('Ananya Rao', 'ananya@example.com', '$2b$12$examplehash1', 'customer'),
    ('Rahul Mehta', 'rahul.admin@example.com', '$2b$12$examplehash2', 'admin');

INSERT INTO complaints (user_id, complaint_text)
VALUES (1, 'My payment was deducted but my laptop hasn''t arrived.');

UPDATE complaints
SET category = 'Delivery Issue',
    department = 'Logistics',
    confidence_score = 0.91,
    extracted_entities = '{"order_id":"ORD4521","product":"Laptop X"}',
    status = 'awaiting_review'
WHERE id = 1;

INSERT INTO responses (complaint_id, ai_draft_response)
VALUES (1, 'As per our shipping policy section 4.2, refunds for undelivered items are processed within 5-7 business days.');

UPDATE responses
SET final_response = 'Your refund of Rs.52,000 has been initiated and will reflect in 5-7 business days per policy 4.2.',
    approved_by = 2,
    approved_at = CURRENT_TIMESTAMP
WHERE complaint_id = 1;

UPDATE complaints SET status = 'resolved' WHERE id = 1;

INSERT INTO policies (title, department, filename, version, uploaded_by)
VALUES ('Shipping & Refund Policy', 'Logistics', 'shipping_refund_v1.pdf', 'v1.0', 2);
