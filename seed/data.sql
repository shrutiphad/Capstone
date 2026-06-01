-- Two tenants. A cross-tenant query must never return the other's rows.
INSERT INTO properties VALUES
 ('hotel_a','Hotel Surya','Varanasi',24),
 ('hotel_b','Coastal Stay PG','Bengaluru',40);

INSERT INTO rooms VALUES
 ('a1','hotel_a','deluxe',2),('a2','hotel_a','standard',2),('a3','hotel_a','suite',3),
 ('b1','hotel_b','standard',1),('b2','hotel_b','standard',2);

INSERT INTO rates VALUES
 ('r1','hotel_a','deluxe','2026-05-30',3200),('r2','hotel_a','standard','2026-05-30',1800),
 ('r3','hotel_a','deluxe','2026-05-31',3600),('r4','hotel_b','standard','2026-05-30',900);

INSERT INTO bookings VALUES
 ('bk1','hotel_a','deluxe','2026-05-02','2026-05-04','checked_out',6400,'mmt'),
 ('bk2','hotel_a','standard','2026-05-10','2026-05-11','confirmed',1800,'direct'),
 ('bk3','hotel_a','deluxe','2026-05-17','2026-05-18','no_show',3200,'booking_com'),
 ('bk4','hotel_a','suite','2026-05-24','2026-05-26','cancelled',8000,'agoda'),
 ('bk5','hotel_a','standard','2026-05-30','2026-05-31','confirmed',1800,'direct'),
 ('bk6','hotel_b','standard','2026-05-03','2026-05-05','checked_out',1800,'direct'),
 ('bk7','hotel_b','standard','2026-05-30','2026-05-31','confirmed',900,'mmt');
