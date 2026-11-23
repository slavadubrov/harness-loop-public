"""Questions about the shop's data. Each has the reference query whose rows are the
expected answer. ``dev`` questions are the ones an improver reads; ``val`` decides whether
a change is kept; ``test`` is scored once at the end."""

from typing import NamedTuple


class Q(NamedTuple):
    id: str
    split: str  # dev, val or test
    question: str
    sql: str  # the reference query
    ordered: bool = False  # the question asks for the rows in an order
    level: str = "easy"  # easy, medium or hard


# Every split has the same mix: a third easy (one table), a third medium (a join or two,
# grouping, NULLs) and a third hard (three tables and more, subqueries, ratios, date
# arithmetic). A fractional answer is always rounded to 2 decimals, and a query that sorts
# its rows sorts them by output columns, so that the tests can look for ties.
QUESTIONS = [
    # dev, easy
    Q(
        "dev-pending-orders",
        "dev",
        "How many orders are still pending?",
        "SELECT COUNT(*) FROM orders WHERE status = 'pending_payment'",
    ),
    Q(
        "dev-refunded-total",
        "dev",
        "How much money have we paid back in refunds so far, in dollars?",
        "SELECT ROUND(SUM(amount_minor) / 100.0, 2) FROM refunds",
    ),
    Q(
        "dev-open-tickets",
        "dev",
        "How many support tickets are still open, meaning not resolved yet?",
        "SELECT COUNT(*) FROM tickets WHERE resolved_at IS NULL",
    ),
    Q(
        "dev-signups-2025",
        "dev",
        "How many of our customers signed up during 2025?",
        "SELECT COUNT(*) FROM customers WHERE signup_date BETWEEN '2025-01-01' AND '2025-12-31'",
    ),
    Q(
        "dev-customers-with-cancellation",
        "dev",
        "How many different customers have had at least one order cancelled?",
        "SELECT COUNT(DISTINCT customer_id) FROM orders WHERE status = 'canceled'",
    ),
    Q(
        "dev-average-rating",
        "dev",
        "What satisfaction score do customers give us on average, over the tickets that were "
        "rated? Round to 2 decimals.",
        "SELECT ROUND(AVG(satisfaction), 2) FROM tickets WHERE satisfaction IS NOT NULL",
    ),
    Q(
        "dev-order-93-merchandise",
        "dev",
        "What is the merchandise value of order 93 in cents: quantity times the unit price "
        "paid, added up over its lines, shipping not included?",
        "SELECT SUM(quantity * unit_price_minor) FROM order_items WHERE order_id = 93",
    ),
    Q(
        "dev-priciest-products",
        "dev",
        "Which five products have the highest list prices? Give the product name and the list "
        "price in dollars, most expensive first; where prices are equal, sort by name from A "
        "to Z.",
        "SELECT name, price_minor / 100.0 AS price FROM products ORDER BY price DESC, name LIMIT 5",
        ordered=True,
    ),
    # dev, medium
    Q(
        "dev-orders-by-country",
        "dev",
        "How many orders have come from customers in each country, counting every order "
        "whatever its status? Give the country code and the number of orders.",
        "SELECT c.country, COUNT(*) FROM orders o JOIN customers c ON c.id = o.customer_id "
        "GROUP BY c.country",
        level="medium",
    ),
    Q(
        "dev-category-revenue",
        "dev",
        "How much did each product category sell for across all orders, whatever their status? "
        "Use the unit prices actually paid times the quantities, and give the category and the "
        "amount in dollars.",
        "SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id GROUP BY p.category",
        level="medium",
    ),
    Q(
        "dev-deliveries-per-month",
        "dev",
        "How many orders were delivered in each month, going by the delivery date? Give the "
        "month as YYYY-MM and the number of orders delivered in it.",
        "SELECT strftime('%Y-%m', delivered_at) AS month, COUNT(*) FROM orders "
        "WHERE delivered_at IS NOT NULL GROUP BY month",
        level="medium",
    ),
    Q(
        "dev-lowest-rated-topic",
        "dev",
        "Which ticket topic gets the lowest average satisfaction score, looking only at the "
        "tickets that were rated? Give the topic and its average rounded to 2 decimals.",
        "SELECT topic, ROUND(AVG(satisfaction), 2) AS average FROM tickets "
        "WHERE satisfaction IS NOT NULL GROUP BY topic ORDER BY average LIMIT 1",
        level="medium",
    ),
    Q(
        "dev-dutch-refund-counts",
        "dev",
        "For each customer in the Netherlands, how many refunds have they received? Include "
        "customers who never got one, and give the customer name and the number of refunds.",
        "SELECT c.name, COUNT(r.id) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id "
        "LEFT JOIN refunds r ON r.order_id = o.id WHERE c.country = 'NLD' GROUP BY c.id",
        level="medium",
    ),
    Q(
        "dev-general-tickets-by-topic",
        "dev",
        "Some tickets are not about any particular order. How many of those do we have per "
        "topic? Give the topic and the count.",
        "SELECT topic, COUNT(*) FROM tickets WHERE order_id IS NULL GROUP BY topic",
        level="medium",
    ),
    Q(
        "dev-audio-buyers",
        "dev",
        "How many different customers have ordered at least one audio product, counting orders "
        "of any status?",
        "SELECT COUNT(DISTINCT o.customer_id) FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
        "WHERE p.category = 'audio_gear'",
        level="medium",
    ),
    Q(
        "dev-discounted-lines",
        "dev",
        "Across all orders, how many order lines were sold for less than the product's current "
        "list price?",
        "SELECT COUNT(*) FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "WHERE oi.unit_price_minor < p.price_minor",
        level="medium",
    ),
    # dev, hard
    Q(
        "dev-never-delivered",
        "dev",
        "Which customers have never had an order delivered? Give their names.",
        "SELECT c.name FROM customers c WHERE NOT EXISTS "
        "(SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.status = 'delivered_complete')",
        level="hard",
    ),
    Q(
        "dev-revenue-by-segment",
        "dev",
        "What revenue did each customer segment bring in from delivered orders? Revenue is "
        "quantity times unit price paid, without shipping. Give the segment and the revenue in "
        "dollars.",
        "SELECT c.segment, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id WHERE o.status = 'delivered_complete' "
        "GROUP BY c.segment",
        level="hard",
    ),
    Q(
        "dev-cancel-rate-by-country",
        "dev",
        "What percentage of orders gets cancelled in each customer country? Give the country "
        "code and the percentage of that country's orders that were cancelled, rounded to 2 "
        "decimals.",
        "SELECT c.country, ROUND(100.0 * SUM(o.status = 'canceled') / COUNT(*), 2) "
        "FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.country",
        level="hard",
    ),
    Q(
        "dev-top-product-per-category",
        "dev",
        "In each product category, which product sold the most units on delivered orders? Give "
        "the category, the product name and the number of units.",
        "WITH sold AS (SELECT p.category, p.name, SUM(oi.quantity) AS units "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status = 'delivered_complete' GROUP BY p.id) "
        "SELECT category, name, units FROM sold s "
        "WHERE units = (SELECT MAX(units) FROM sold t WHERE t.category = s.category)",
        level="hard",
    ),
    Q(
        "dev-frequent-buyers",
        "dev",
        "Which customers have more than eight orders that were not cancelled? Give the "
        "customer name and the number of such orders.",
        "SELECT c.name, COUNT(*) FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status <> 'canceled' GROUP BY c.id HAVING COUNT(*) > 8",
        level="hard",
    ),
    Q(
        "dev-resolution-days-by-topic",
        "dev",
        "How long do we take to resolve a ticket, per topic? Take the resolved tickets only and "
        "give the topic and the average number of days from opening to resolution, rounded to "
        "2 decimals. A ticket resolved on the day it was opened took 0 days.",
        "SELECT topic, ROUND(AVG(julianday(resolved_at) - julianday(opened_at)), 2) "
        "FROM tickets WHERE resolved_at IS NOT NULL GROUP BY topic",
        level="hard",
    ),
    Q(
        "dev-orders-above-average",
        "dev",
        "Take the merchandise value of every order, whatever its status: quantity times unit "
        "price paid, summed over its lines, without shipping. How many orders are worth more "
        "than the average order?",
        "WITH worth AS (SELECT order_id, SUM(quantity * unit_price_minor) AS minor "
        "FROM order_items GROUP BY order_id) "
        "SELECT COUNT(*) FROM worth WHERE minor > (SELECT AVG(minor) FROM worth)",
        level="hard",
    ),
    Q(
        "dev-largest-charges",
        "dev",
        "Which three orders, of any status, have the largest total charge, where the total "
        "charge is the merchandise value (quantity times unit price paid) plus the order's "
        "shipping fee? Give the order id and the total in dollars, largest first.",
        "SELECT o.id, (SUM(oi.quantity * oi.unit_price_minor) + o.shipping_minor) / 100.0 "
        "AS total FROM orders o JOIN order_items oi ON oi.order_id = o.id GROUP BY o.id "
        "ORDER BY total DESC LIMIT 3",
        ordered=True,
        level="hard",
    ),
    # val, easy
    Q(
        "val-orders-by-status",
        "val",
        "Break our orders down by status: how many orders are there in each? Give the status "
        "and the count.",
        "SELECT status, COUNT(*) FROM orders GROUP BY status",
    ),
    Q(
        "val-average-refund",
        "val",
        "What is the average size of a refund, in dollars rounded to 2 decimals?",
        "SELECT ROUND(AVG(amount_minor) / 100.0, 2) FROM refunds",
    ),
    Q(
        "val-products-over-100",
        "val",
        "Which products have a list price above 100 dollars? Give the product name and the "
        "list price in dollars.",
        "SELECT name, price_minor / 100.0 FROM products WHERE price_minor > 10000",
    ),
    Q(
        "val-resolved-unrated",
        "val",
        "How many tickets have been resolved but never received a satisfaction rating?",
        "SELECT COUNT(*) FROM tickets WHERE resolved_at IS NOT NULL AND satisfaction IS NULL",
    ),
    Q(
        "val-latest-delivery",
        "val",
        "On what date did our most recent delivery take place? Give the date as YYYY-MM-DD.",
        "SELECT MAX(date(delivered_at)) FROM orders",
    ),
    Q(
        "val-q2-orders",
        "val",
        "How many orders were placed in the second quarter of 2026, April through June?",
        "SELECT COUNT(*) FROM orders WHERE date(placed_at) BETWEEN '2026-04-01' AND '2026-06-30'",
    ),
    Q(
        "val-walsh-customers",
        "val",
        "Which customers have the family name Walsh? Give the full name and the country code.",
        "SELECT name, country FROM customers WHERE name LIKE '% Walsh'",
    ),
    Q(
        "val-ticket-customers",
        "val",
        "How many different customers have ever opened a support ticket?",
        "SELECT COUNT(DISTINCT customer_id) FROM tickets",
    ),
    Q(
        "val-largest-line",
        "val",
        "Across all orders, what is the most that a single order line has come to, in dollars? "
        "A line comes to its quantity times the unit price paid.",
        "SELECT MAX(quantity * unit_price_minor) / 100.0 FROM order_items",
    ),
    Q(
        "val-cheapest-products",
        "val",
        "Which products have the lowest list price in the catalogue? Give the names of all "
        "products at that price.",
        "SELECT name FROM products WHERE price_minor = (SELECT MIN(price_minor) FROM products)",
    ),
    Q(
        "val-largest-refunds",
        "val",
        "What were the three largest refunds? Give the refund id and the amount in dollars, "
        "largest first.",
        "SELECT id, amount_minor / 100.0 AS amount FROM refunds ORDER BY amount DESC LIMIT 3",
        ordered=True,
    ),
    Q(
        "val-customers-by-country",
        "val",
        "How many customers do we have in each country? Give the country code and the number "
        "of customers.",
        "SELECT country, COUNT(*) FROM customers GROUP BY country",
    ),
    # val, medium
    Q(
        "val-general-ticket-share",
        "val",
        "What share of all tickets is not about any order? Give it as a percentage rounded to "
        "2 decimals.",
        "SELECT ROUND(100.0 * SUM(order_id IS NULL) / COUNT(*), 2) FROM tickets",
        level="medium",
    ),
    Q(
        "val-multi-product-orders",
        "val",
        "How many orders, of any status, contain three or more different products?",
        "SELECT COUNT(*) FROM "
        "(SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) >= 3)",
        level="medium",
    ),
    Q(
        "val-total-discount",
        "val",
        "How much discount have we given in total across all order lines, in dollars? The "
        "discount on a line is the product's current list price minus the unit price paid, "
        "times the quantity.",
        "SELECT ROUND(SUM((p.price_minor - oi.unit_price_minor) * oi.quantity) / 100.0, 2) "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id",
        level="medium",
    ),
    Q(
        "val-tickets-per-month",
        "val",
        "For each month in which tickets were opened, how many were opened and how many of "
        "those are still open? Give the month as YYYY-MM, the number opened and the number "
        "still open.",
        "SELECT strftime('%Y-%m', opened_at) AS month, COUNT(*), SUM(resolved_at IS NULL) "
        "FROM tickets GROUP BY month",
        level="medium",
    ),
    Q(
        "val-german-delivered-buyers",
        "val",
        "How many different customers in Germany have at least one delivered order?",
        "SELECT COUNT(DISTINCT c.id) FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE c.country = 'DEU' AND o.status = 'delivered_complete'",
        level="medium",
    ),
    Q(
        "val-rating-by-segment",
        "val",
        "What is the average satisfaction score by customer segment, over rated tickets only? "
        "Give the segment and the average rounded to 2 decimals.",
        "SELECT c.segment, ROUND(AVG(t.satisfaction), 2) FROM tickets t "
        "JOIN customers c ON c.id = t.customer_id WHERE t.satisfaction IS NOT NULL "
        "GROUP BY c.segment",
        level="medium",
    ),
    Q(
        "val-refunds-on-january-orders",
        "val",
        "How much has been refunded on orders that were placed in January 2026, in dollars?",
        "SELECT ROUND(SUM(r.amount_minor) / 100.0, 2) FROM refunds r "
        "JOIN orders o ON o.id = r.order_id "
        "WHERE date(o.placed_at) BETWEEN '2026-01-01' AND '2026-01-31'",
        level="medium",
    ),
    Q(
        "val-mona-park-orders",
        "val",
        "What was the merchandise value of each of Mona Park's orders, whatever their status? "
        "Use quantity times unit price paid, without shipping, and give the order id and the "
        "value in dollars.",
        "SELECT o.id, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id WHERE c.name = 'Mona Park' GROUP BY o.id",
        level="medium",
    ),
    Q(
        "val-reseller-ticket-counts",
        "val",
        "How many support tickets has each of our resellers opened? Include resellers who have "
        "opened none, and give the customer name and the number of tickets.",
        "SELECT c.name, COUNT(t.id) FROM customers c LEFT JOIN tickets t ON t.customer_id = c.id "
        "WHERE c.segment = 'reseller_partner' GROUP BY c.id",
        level="medium",
    ),
    Q(
        "val-revenue-by-status",
        "val",
        "How much merchandise value sits in orders of each status? Add up quantity times unit "
        "price paid, without shipping, and give the status and the amount in dollars.",
        "SELECT o.status, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id GROUP BY o.status",
        level="medium",
    ),
    Q(
        "val-recent-buyers",
        "val",
        "Which customers placed an order on 17 June 2026 or later? Give each customer's name once.",
        "SELECT DISTINCT c.name FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE date(o.placed_at) >= '2026-06-17'",
        level="medium",
    ),
    Q(
        "val-tickets-on-refunded-orders",
        "val",
        "How many tickets are about an order that has been refunded?",
        "SELECT COUNT(*) FROM tickets WHERE order_id IN (SELECT order_id FROM refunds)",
        level="medium",
    ),
    # val, hard
    Q(
        "val-no-tickets",
        "val",
        "Which customers have never opened a support ticket? Give the customer name and the "
        "country code.",
        "SELECT c.name, c.country FROM customers c WHERE NOT EXISTS "
        "(SELECT 1 FROM tickets t WHERE t.customer_id = c.id)",
        level="hard",
    ),
    Q(
        "val-top-customers-delivered",
        "val",
        "Who are our five best customers by revenue from delivered orders (quantity times unit "
        "price paid, shipping excluded)? Give the customer name and the revenue in dollars, "
        "highest first.",
        "SELECT c.name, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) AS revenue "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id WHERE o.status = 'delivered_complete' "
        "GROUP BY c.id ORDER BY revenue DESC LIMIT 5",
        ordered=True,
        level="hard",
    ),
    Q(
        "val-refunded-order-share",
        "val",
        "What percentage of delivered orders has been refunded, fully or partly? Round to 2 "
        "decimals.",
        "SELECT ROUND(100.0 * COUNT(r.id) / COUNT(*), 2) FROM orders o "
        "LEFT JOIN refunds r ON r.order_id = o.id WHERE o.status = 'delivered_complete'",
        level="hard",
    ),
    Q(
        "val-top-customer-per-country",
        "val",
        "In each country, which customer has spent the most on delivered orders (quantity "
        "times unit price paid, without shipping)? Give the country code, the customer name "
        "and the amount in dollars.",
        "WITH spent AS (SELECT c.id, c.country, c.name, "
        "SUM(oi.quantity * oi.unit_price_minor) AS minor FROM customers c "
        "JOIN orders o ON o.customer_id = c.id JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.status = 'delivered_complete' GROUP BY c.id) "
        "SELECT country, name, minor / 100.0 FROM spent s "
        "WHERE minor = (SELECT MAX(minor) FROM spent t WHERE t.country = s.country)",
        level="hard",
    ),
    Q(
        "val-popular-products",
        "val",
        "Which products appear on at least 25 orders, counting orders of any status? Give the "
        "product name and the number of orders it appears on.",
        "SELECT p.name, COUNT(*) FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "GROUP BY p.id HAVING COUNT(*) >= 25",
        level="hard",
    ),
    Q(
        "val-delivery-days-by-country",
        "val",
        "How many days does delivery take on average in each customer country, from the order "
        "date to the delivery date? Use delivered orders, and give the country code and the "
        "average rounded to 2 decimals.",
        "SELECT c.country, ROUND(AVG(julianday(o.delivered_at) - julianday(o.placed_at)), 2) "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "WHERE o.status = 'delivered_complete' GROUP BY c.country",
        level="hard",
    ),
    Q(
        "val-overdue-shipments",
        "val",
        "Which orders currently in transit were placed more than 120 days before 2026-06-30? "
        "Give the order id, the customer name and the number of days from the order date to "
        "2026-06-30 (an order placed on 2026-06-29 would count 1 day), longest wait first; "
        "when two waits are equal, the lower order id goes first.",
        "SELECT o.id AS order_id, c.name, "
        "CAST(julianday('2026-06-30') - julianday(date(o.placed_at)) AS INTEGER) AS days "
        "FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.status = 'in_transit' "
        "AND julianday('2026-06-30') - julianday(date(o.placed_at)) > 120 "
        "ORDER BY days DESC, order_id",
        ordered=True,
        level="hard",
    ),
    Q(
        "val-above-category-average",
        "val",
        "Which products are priced above the average list price of their own category? Give "
        "the product name and the category.",
        "SELECT p.name, p.category FROM products p WHERE p.price_minor > "
        "(SELECT AVG(q.price_minor) FROM products q WHERE q.category = p.category)",
        level="hard",
    ),
    Q(
        "val-pending-total-charge",
        "val",
        "What is the total charge on all pending orders taken together, in dollars? Count the "
        "merchandise (quantity times unit price paid) plus the shipping fee of each order.",
        "SELECT ROUND((SUM(worth.minor) + SUM(o.shipping_minor)) / 100.0, 2) FROM orders o "
        "JOIN (SELECT order_id, SUM(quantity * unit_price_minor) AS minor FROM order_items "
        "GROUP BY order_id) worth ON worth.order_id = o.id WHERE o.status = 'pending_payment'",
        level="hard",
    ),
    Q(
        "val-active-five-months",
        "val",
        "How many customers placed orders in at least five different calendar months?",
        "SELECT COUNT(*) FROM (SELECT customer_id FROM orders GROUP BY customer_id "
        "HAVING COUNT(DISTINCT strftime('%Y-%m', placed_at)) >= 5)",
        level="hard",
    ),
    Q(
        "val-discount-rate-by-category",
        "val",
        "On delivered orders, how big was the discount in each product category, as a "
        "percentage of the list-price value? Compare what the lines would have cost at current "
        "list prices with what was actually paid, and give the category and the percentage "
        "rounded to 2 decimals.",
        "SELECT p.category, ROUND(100.0 * SUM((p.price_minor - oi.unit_price_minor) * "
        "oi.quantity) / SUM(p.price_minor * oi.quantity), 2) FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status = 'delivered_complete' GROUP BY p.category",
        level="hard",
    ),
    Q(
        "val-products-never-cancelled",
        "val",
        "Which products have never been part of a cancelled order? Give the product names.",
        "SELECT p.name FROM products p WHERE NOT EXISTS (SELECT 1 FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "WHERE oi.product_id = p.id AND o.status = 'canceled')",
        level="hard",
    ),
    # test, easy
    Q(
        "test-delivered-free-shipping",
        "test",
        "How many delivered orders went out with free shipping?",
        "SELECT COUNT(*) FROM orders WHERE status = 'delivered_complete' AND shipping_minor = 0",
    ),
    Q(
        "test-march-shipping",
        "test",
        "How much did we charge for shipping on orders placed in March 2026, in dollars? "
        "Include every order placed that month, whatever its status.",
        "SELECT ROUND(SUM(shipping_minor) / 100.0, 2) FROM orders "
        "WHERE date(placed_at) BETWEEN '2026-03-01' AND '2026-03-31'",
    ),
    Q(
        "test-refunds-over-250",
        "test",
        "How many refunds were for more than 250 dollars?",
        "SELECT COUNT(*) FROM refunds WHERE amount_minor > 25000",
    ),
    Q(
        "test-no-delivery-date",
        "test",
        "How many orders have no delivery date on record?",
        "SELECT COUNT(*) FROM orders WHERE delivered_at IS NULL",
    ),
    Q(
        "test-open-general-tickets",
        "test",
        "Of the tickets that are not linked to any order, how many are still open?",
        "SELECT COUNT(*) FROM tickets WHERE order_id IS NULL AND resolved_at IS NULL",
    ),
    Q(
        "test-average-price-by-category",
        "test",
        "What is the average list price in each product category? Give the category and the "
        "average in dollars, rounded to 2 decimals.",
        "SELECT category, ROUND(AVG(price_minor) / 100.0, 2) FROM products GROUP BY category",
    ),
    Q(
        "test-tickets-since-mid-may",
        "test",
        "How many tickets have been opened since 15 May 2026, that day included?",
        "SELECT COUNT(*) FROM tickets WHERE date(opened_at) >= '2026-05-15'",
    ),
    Q(
        "test-order-days",
        "test",
        "On how many different days was at least one order placed?",
        "SELECT COUNT(DISTINCT date(placed_at)) FROM orders",
    ),
    Q(
        "test-big-lines",
        "test",
        "Across all orders, how many order lines are worth 500 dollars or more, where a line "
        "is worth its quantity times the unit price paid?",
        "SELECT COUNT(*) FROM order_items WHERE quantity * unit_price_minor >= 50000",
    ),
    Q(
        "test-us-business-customers",
        "test",
        "Which of our business customers are in the United States? Give their names.",
        "SELECT name FROM customers WHERE segment = 'b2b_account' AND country = 'USA'",
    ),
    Q(
        "test-oldest-open-tickets",
        "test",
        "Which four open tickets have been waiting the longest? Give the ticket id and the "
        "date it was opened (YYYY-MM-DD), oldest first; when two were opened on the same day, "
        "the lower ticket id goes first.",
        "SELECT id, date(opened_at) AS opened_at FROM tickets WHERE resolved_at IS NULL "
        "ORDER BY opened_at, id LIMIT 4",
        ordered=True,
    ),
    Q(
        "test-tickets-by-topic",
        "test",
        "How many tickets have we had on each topic? Give the topic and the number of tickets.",
        "SELECT topic, COUNT(*) FROM tickets GROUP BY topic",
    ),
    # test, medium
    Q(
        "test-most-ordered-products",
        "test",
        "Which four products have been ordered in the largest quantities, adding up the units "
        "over all orders whatever their status? Give the product name and the total units, "
        "most units first; products with equal units go in alphabetical order.",
        "SELECT p.name, SUM(oi.quantity) AS units FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id GROUP BY p.id "
        "ORDER BY units DESC, name LIMIT 4",
        ordered=True,
        level="medium",
    ),
    Q(
        "test-kitchen-list-vs-lowest-paid",
        "test",
        "For each kitchen product, how does the list price compare with the lowest unit price "
        "anyone has paid for it on any order? Give the product name, the list price and the "
        "lowest price paid, both prices in dollars.",
        "SELECT p.name, p.price_minor / 100.0, MIN(oi.unit_price_minor) / 100.0 "
        "FROM products p JOIN order_items oi ON oi.product_id = p.id "
        "WHERE p.category = 'kitchen_dining' GROUP BY p.id",
        level="medium",
    ),
    Q(
        "test-refunds-per-month",
        "test",
        "For each month in which refunds were issued, how many were there and how much money "
        "was refunded? Give the month as YYYY-MM, the number of refunds and the total in "
        "dollars.",
        "SELECT strftime('%Y-%m', created_at) AS month, COUNT(*), "
        "ROUND(SUM(amount_minor) / 100.0, 2) FROM refunds GROUP BY month",
        level="medium",
    ),
    Q(
        "test-refunded-customers",
        "test",
        "How many different customers have received at least one refund?",
        "SELECT COUNT(DISTINCT o.customer_id) FROM refunds r JOIN orders o ON o.id = r.order_id",
        level="medium",
    ),
    Q(
        "test-high-rating-share",
        "test",
        "Among the tickets that were rated, what percentage got a score of 4 or 5? Round to 2 "
        "decimals.",
        "SELECT ROUND(100.0 * SUM(satisfaction >= 4) / COUNT(*), 2) FROM tickets "
        "WHERE satisfaction IS NOT NULL",
        level="medium",
    ),
    Q(
        "test-refunds-to-business",
        "test",
        "How many refunds went to business customers?",
        "SELECT COUNT(*) FROM refunds r JOIN orders o ON o.id = r.order_id "
        "JOIN customers c ON c.id = o.customer_id WHERE c.segment = 'b2b_account'",
        level="medium",
    ),
    Q(
        "test-olga-meyer-orders",
        "test",
        "How many orders has Olga Meyer placed altogether, and how many of them were "
        "cancelled? Give the two numbers in one row.",
        "SELECT COUNT(*), SUM(o.status = 'canceled') FROM orders o "
        "JOIN customers c ON c.id = o.customer_id WHERE c.name = 'Olga Meyer'",
        level="medium",
    ),
    Q(
        "test-sweden-cancellations",
        "test",
        "For each customer in Sweden, how many of their orders were cancelled? Include the "
        "customers with no cancelled orders, and give the customer name and the count.",
        "SELECT c.name, COUNT(o.id) FROM customers c "
        "LEFT JOIN orders o ON o.customer_id = c.id AND o.status = 'canceled' "
        "WHERE c.country = 'SWE' GROUP BY c.id",
        level="medium",
    ),
    Q(
        "test-average-cancelled-order",
        "test",
        "What is the average merchandise value of a cancelled order, in dollars rounded to 2 "
        "decimals? An order's merchandise value is quantity times unit price paid, summed over "
        "its lines, without shipping.",
        "SELECT ROUND(AVG(minor) / 100.0, 2) FROM "
        "(SELECT SUM(oi.quantity * oi.unit_price_minor) AS minor FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id WHERE o.status = 'canceled' GROUP BY o.id)",
        level="medium",
    ),
    Q(
        "test-orders-from-2024-signups",
        "test",
        "How many orders were placed by customers who signed up in 2024?",
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.id = o.customer_id "
        "WHERE c.signup_date BETWEEN '2024-01-01' AND '2024-12-31'",
        level="medium",
    ),
    Q(
        "test-shipping-by-country",
        "test",
        "How much shipping have customers in each country been charged on orders that were not "
        "cancelled? Give the country code and the shipping total in dollars.",
        "SELECT c.country, ROUND(SUM(o.shipping_minor) / 100.0, 2) FROM orders o "
        "JOIN customers c ON c.id = o.customer_id WHERE o.status <> 'canceled' "
        "GROUP BY c.country",
        level="medium",
    ),
    Q(
        "test-orders-with-tickets",
        "test",
        "How many different orders have had at least one support ticket raised about them?",
        "SELECT COUNT(DISTINCT order_id) FROM tickets WHERE order_id IS NOT NULL",
        level="medium",
    ),
    # test, hard
    Q(
        "test-quiet-in-june",
        "test",
        "Which customers placed no order at all in June 2026? Give their names.",
        "SELECT c.name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o "
        "WHERE o.customer_id = c.id AND date(o.placed_at) BETWEEN '2026-06-01' AND '2026-06-30')",
        level="hard",
    ),
    Q(
        "test-german-revenue-by-category",
        "test",
        "For our customers in Germany, what revenue did each product category bring in on "
        "delivered orders (quantity times unit price paid, no shipping)? Give the category and "
        "the revenue in dollars.",
        "SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price_minor) / 100.0, 2) "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
        "WHERE c.country = 'DEU' AND o.status = 'delivered_complete' GROUP BY p.category",
        level="hard",
    ),
    Q(
        "test-open-share-by-topic",
        "test",
        "For each ticket topic, what percentage of its tickets is still open? Give the topic "
        "and the percentage rounded to 2 decimals.",
        "SELECT topic, ROUND(100.0 * SUM(resolved_at IS NULL) / COUNT(*), 2) FROM tickets "
        "GROUP BY topic",
        level="hard",
    ),
    Q(
        "test-top-category-per-month",
        "test",
        "For each month in which orders were placed, which product category brought in the "
        "most revenue on orders that were not cancelled? Revenue is quantity times unit price "
        "paid. Give the month as YYYY-MM, the category and its revenue in dollars.",
        "WITH sales AS (SELECT strftime('%Y-%m', o.placed_at) AS month, p.category, "
        "SUM(oi.quantity * oi.unit_price_minor) AS minor FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
        "WHERE o.status <> 'canceled' GROUP BY month, p.category) "
        "SELECT month, category, minor / 100.0 FROM sales s "
        "WHERE minor = (SELECT MAX(minor) FROM sales t WHERE t.month = s.month)",
        level="hard",
    ),
    Q(
        "test-all-category-buyers",
        "test",
        "Which customers have bought from all six product categories, counting only their "
        "delivered orders? Give their names.",
        "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id "
        "WHERE o.status = 'delivered_complete' GROUP BY c.id HAVING COUNT(DISTINCT p.category) = 6",
        level="hard",
    ),
    Q(
        "test-slow-deliveries",
        "test",
        "How many delivered orders took more than 7 days from the order date to the delivery date?",
        "SELECT COUNT(*) FROM orders WHERE status = 'delivered_complete' "
        "AND julianday(delivered_at) - julianday(placed_at) > 7",
        level="hard",
    ),
    Q(
        "test-refund-lag",
        "test",
        "On average, how many days after an order's delivery was its refund issued? Round to 2 "
        "decimals.",
        "SELECT ROUND(AVG(julianday(r.created_at) - julianday(o.delivered_at)), 2) "
        "FROM refunds r JOIN orders o ON o.id = r.order_id",
        level="hard",
    ),
    Q(
        "test-last-order-cancelled",
        "test",
        "For which customers is the most recently placed order a cancelled one? Give their names.",
        "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status = 'canceled' AND o.placed_at = "
        "(SELECT MAX(x.placed_at) FROM orders x WHERE x.customer_id = c.id)",
        level="hard",
    ),
    Q(
        "test-biggest-spender-with-shipping",
        "test",
        "Which customer has been charged the most in total on orders that were not cancelled, "
        "counting merchandise (quantity times unit price paid) plus shipping fees? Give the "
        "customer name and the total in dollars.",
        "SELECT c.name, ROUND(SUM(worth.minor + o.shipping_minor) / 100.0, 2) AS total "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "JOIN (SELECT order_id, SUM(quantity * unit_price_minor) AS minor FROM order_items "
        "GROUP BY order_id) worth ON worth.order_id = o.id WHERE o.status <> 'canceled' "
        "GROUP BY c.id ORDER BY total DESC LIMIT 1",
        level="hard",
    ),
    Q(
        "test-net-revenue-by-month",
        "test",
        "For each month in which orders were placed, what is the revenue from that month's "
        "delivered orders (quantity times unit price paid, no shipping) minus the refunds "
        "given on those orders? Give the month as YYYY-MM and the net amount in dollars.",
        "WITH worth AS (SELECT order_id, SUM(quantity * unit_price_minor) AS minor "
        "FROM order_items GROUP BY order_id) "
        "SELECT strftime('%Y-%m', o.placed_at) AS month, "
        "ROUND((SUM(w.minor) - SUM(COALESCE(r.amount_minor, 0))) / 100.0, 2) FROM orders o "
        "JOIN worth w ON w.order_id = o.id LEFT JOIN refunds r ON r.order_id = o.id "
        "WHERE o.status = 'delivered_complete' GROUP BY month",
        level="hard",
    ),
    Q(
        "test-mostly-discounted-products",
        "test",
        "Which products were sold below their current list price on more than 45 percent of "
        "their order lines, counting all orders? Give the product name and that percentage "
        "rounded to 2 decimals.",
        "SELECT p.name, ROUND(100.0 * SUM(oi.unit_price_minor < p.price_minor) / COUNT(*), 2) "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id GROUP BY p.id "
        "HAVING 100.0 * SUM(oi.unit_price_minor < p.price_minor) / COUNT(*) > 45",
        level="hard",
    ),
    Q(
        "test-reseller-first-order-lag",
        "test",
        "For each reseller, how many days passed between signing up and placing their first "
        "order, whatever that order's status? Give the customer name and the number of days, "
        "shortest wait first.",
        "SELECT c.name, "
        "CAST(julianday(MIN(date(o.placed_at))) - julianday(c.signup_date) AS INTEGER) AS days "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE c.segment = 'reseller_partner' GROUP BY c.id ORDER BY days",
        ordered=True,
        level="hard",
    ),
]
