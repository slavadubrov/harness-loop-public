# sql-desk, 000: 16 of 24 tasks pass every run (success 0.67)

## dev-pending-orders: 0 of 3 runs passed
Tags: easy
Input:
> How many orders are still pending?
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT COUNT(*) AS pending_orders
> FROM orders
> WHERE status = 'pending';
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[22.0]]}

Run 1 ended `completed`. Reply:
> SELECT COUNT(*) AS pending_orders
> FROM orders
> WHERE status = 'pending';
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[22.0]]}

## dev-customers-with-cancellation: 0 of 3 runs passed
Tags: easy
Input:
> How many different customers have had at least one order cancelled?
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT COUNT(DISTINCT customer_id) AS customer_count
> FROM orders
> WHERE status = 'cancelled';
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[25.0]]}

Run 1 ended `completed`. Reply:
> SELECT COUNT(DISTINCT customer_id)
> FROM orders
> WHERE status = 'cancelled';
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[25.0]]}

## dev-dutch-refund-counts: 0 of 3 runs passed
Tags: medium
Input:
> For each customer in the Netherlands, how many refunds have they received? Include customers who never got one, and give the customer name and the number of refunds.
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT c.name, COUNT(r.id) AS refund_count
> FROM customers AS c
> LEFT JOIN orders AS o ON o.customer_id = c.id
> LEFT JOIN refunds AS r ON r.order_id = o.id
> WHERE c.country = 'Netherlands'
> GROUP BY c.id, c.name;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 3, "expected_first_rows": [["Olga Kowalski", 2.0], ["Pavel Haddad", 0.0], ["Rosa Walsh", 4.0]]}

Run 1 ended `completed`. Reply:
> SELECT c.name, COUNT(r.id) AS refund_count
> FROM customers AS c
> LEFT JOIN orders AS o ON o.customer_id = c.id
> LEFT JOIN refunds AS r ON r.order_id = o.id
> WHERE c.country = 'Netherlands'
> GROUP BY c.id, c.name;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 3, "expected_first_rows": [["Olga Kowalski", 2.0], ["Pavel Haddad", 0.0], ["Rosa Walsh", 4.0]]}

## dev-audio-buyers: 0 of 3 runs passed
Tags: medium
Input:
> How many different customers have ordered at least one audio product, counting orders of any status?
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT COUNT(DISTINCT o.customer_id)
> FROM orders AS o
> JOIN order_items AS oi ON oi.order_id = o.id
> JOIN products AS p ON p.id = oi.product_id
> WHERE p.category = 'audio' COLLATE NOCASE;
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[45.0]]}

Run 1 ended `completed`. Reply:
> SELECT COUNT(DISTINCT o.customer_id)
> FROM orders AS o
> JOIN order_items AS oi ON oi.order_id = o.id
> JOIN products AS p ON p.id = oi.product_id
> WHERE p.category = 'audio' COLLATE NOCASE;
Recorded actions: none
Trace: {"rows": [[0]], "sql_error": null, "expected_rows": 1, "expected_first_rows": [[45.0]]}

## dev-revenue-by-segment: 0 of 3 runs passed
Tags: hard
Input:
> What revenue did each customer segment bring in from delivered orders? Revenue is quantity times unit price paid, without shipping. Give the segment and the revenue in dollars.
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT c.segment,
>        SUM(oi.quantity * oi.unit_price_minor) / 100.0 AS revenue_dollars
> FROM customers AS c
> JOIN orders AS o ON o.customer_id = c.id
> JOIN order_items AS oi ON oi.order_id = o.id
> WHERE o.status = 'delivered'
> GROUP BY c.segment;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 3, "expected_first_rows": [["b2b_account", 26598.7], ["consumer_direct", 55173.3], ["reseller_partner", 19463.6]]}

Run 1 ended `completed`. Reply:
> SELECT c.segment,
>        SUM(oi.quantity * oi.unit_price_minor) / 100.0 AS revenue_dollars
> FROM customers AS c
> JOIN orders AS o ON o.customer_id = c.id
> JOIN order_items AS oi ON oi.order_id = o.id
> WHERE o.status = 'delivered'
> GROUP BY c.segment;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 3, "expected_first_rows": [["b2b_account", 26598.7], ["consumer_direct", 55173.3], ["reseller_partner", 19463.6]]}

## dev-cancel-rate-by-country: 0 of 3 runs passed
Tags: hard
Input:
> What percentage of orders gets cancelled in each customer country? Give the country code and the percentage of that country's orders that were cancelled, rounded to 2 decimals.
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT c.country AS country_code,
>        ROUND(100.0 * AVG(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END), 2) AS cancelled_percentage
> FROM orders AS o
> JOIN customers AS c ON c.id = o.customer_id
> GROUP BY c.country;
Recorded actions: none
Trace: {"rows": [["DEU", 0.0], ["ESP", 0.0], ["FRA", 0.0], ["NLD", 0.0], ["POL", 0.0], ["SWE", 0.0], ["USA", 0.0]], "sql_error": null, "expected_rows": 7, "expected_first_rows": [["DEU", 10.0], ["ESP", 11.11], ["FRA", 13.43], ["NLD", 5.88], ["POL", 12.0]]}

Run 1 ended `completed`. Reply:
> SELECT
>     c.country AS country_code,
>     ROUND(100.0 * AVG(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END), 2) AS cancelled_percentage
> FROM orders AS o
> JOIN customers AS c ON c.id = o.customer_id
> GROUP BY c.country;
Recorded actions: none
Trace: {"rows": [["DEU", 0.0], ["ESP", 0.0], ["FRA", 0.0], ["NLD", 0.0], ["POL", 0.0], ["SWE", 0.0], ["USA", 0.0]], "sql_error": null, "expected_rows": 7, "expected_first_rows": [["DEU", 10.0], ["ESP", 11.11], ["FRA", 13.43], ["NLD", 5.88], ["POL", 12.0]]}

## dev-top-product-per-category: 0 of 3 runs passed
Tags: hard
Input:
> In each product category, which product sold the most units on delivered orders? Give the category, the product name and the number of units.
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> WITH product_sales AS (
>     SELECT p.category, p.name AS product_name, SUM(oi.quantity) AS units
>     FROM products AS p
>     JOIN order_items AS oi ON oi.product_id = p.id
>     JOIN orders AS o ON o.id = oi.order_id
>     WHERE o.status = 'delivered'
>     GROUP BY p.id, p.category, p.name
> ),
> ranked AS (
>     SELECT category, product_name, units,
>            RANK() OVER (PARTITION BY category ORDER BY units DESC) AS sales_rank
>     FROM product_sales
> )
> SELECT category, product_name, units
> FROM ranked
> WHERE sales_rank = 1
> ORDER BY category, product_name;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 6, "expected_first_rows": [["audio_gear", "Studio microphone", 32.0], ["home_decor", "Floor lamp", 33.0], ["home_office", "Office chair", 41.0], ["kids_toys", "Board game", 47.0], ["kitchen_dining", "Ceramic teapot", 38.0]]}

Run 1 ended `completed`. Reply:
> WITH product_sales AS (
>     SELECT p.id, p.category, p.name, SUM(oi.quantity) AS units
>     FROM products AS p
>     JOIN order_items AS oi ON oi.product_id = p.id
>     JOIN orders AS o ON o.id = oi.order_id
>     WHERE o.status = 'delivered'
>     GROUP BY p.id, p.category, p.name
> ),
> ranked AS (
>     SELECT category, name, units,
>            RANK() OVER (PARTITION BY category ORDER BY units DESC) AS sales_rank
>     FROM product_sales
> )
> SELECT category, name AS product_name, units
> FROM ranked
> WHERE sales_rank = 1
> ORDER BY category, product_name;
Recorded actions: none
Trace: {"rows": [], "sql_error": null, "expected_rows": 6, "expected_first_rows": [["audio_gear", "Studio microphone", 32.0], ["home_decor", "Floor lamp", 33.0], ["home_office", "Office chair", 41.0], ["kids_toys", "Board game", 47.0], ["kitchen_dining", "Ceramic teapot", 38.0]]}

## dev-frequent-buyers: 0 of 3 runs passed
Tags: hard
Input:
> Which customers have more than eight orders that were not cancelled? Give the customer name and the number of such orders.
Failed checks:
- `answers with the expected rows` in 3 of 3 runs

Run 0 ended `completed`. Reply:
> SELECT c.name, COUNT(*) AS order_count
> FROM customers AS c
> JOIN orders AS o ON o.customer_id = c.id
> WHERE o.status <> 'cancelled'
> GROUP BY c.id, c.name
> HAVING COUNT(*) > 8;
Recorded actions: none
Trace: {"rows": [["Hugo Lindqvist", 9], ["Liam Laurent", 14], ["Rosa Sokolov", 9], ["Kira Marin", 12], ["Tara Becker", 9], ["Ana Meyer", 14], ["Ana Sokolov", 9], ["Rosa Walsh", 10], ["Ben Sokolov", 9], ["Olga Jensen", 9], ["Olga Meyer", 12]], "sql_error": null, "expected_rows": 7, "expected_first_rows": [["Ana Meyer", 12.0], ["Hugo Lindqvist", 9.0], ["Kira Marin", 9.0], ["Liam Laurent", 14.0], ["Olga Meyer", 10.0]]}

Run 1 ended `completed`. Reply:
> SELECT c.name, COUNT(*) AS order_count
> FROM customers AS c
> JOIN orders AS o ON o.customer_id = c.id
> WHERE o.status <> 'cancelled'
> GROUP BY c.id, c.name
> HAVING COUNT(*) > 8;
Recorded actions: none
Trace: {"rows": [["Hugo Lindqvist", 9], ["Liam Laurent", 14], ["Rosa Sokolov", 9], ["Kira Marin", 12], ["Tara Becker", 9], ["Ana Meyer", 14], ["Ana Sokolov", 9], ["Rosa Walsh", 10], ["Ben Sokolov", 9], ["Olga Jensen", 9], ["Olga Meyer", 12]], "sql_error": null, "expected_rows": 7, "expected_first_rows": [["Ana Meyer", 12.0], ["Hugo Lindqvist", 9.0], ["Kira Marin", 9.0], ["Liam Laurent", 14.0], ["Olga Meyer", 10.0]]}

## Passing every run
dev-refunded-total, dev-open-tickets, dev-signups-2025, dev-average-rating, dev-order-93-merchandise, dev-priciest-products, dev-orders-by-country, dev-category-revenue, dev-deliveries-per-month, dev-lowest-rated-topic, dev-general-tickets-by-topic, dev-discounted-lines, dev-never-delivered, dev-resolution-days-by-topic, dev-orders-above-average, dev-largest-charges
