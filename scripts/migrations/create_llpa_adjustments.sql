-- ============================================================
-- llpa_adjustments  (Loan-Level Price Adjustments)
-- ------------------------------------------------------------
-- Fannie/Freddie add an LLPA to the par base rate based on
-- FICO x LTV x property type x purpose. Without it, quoted rates
-- are wrong by 0.25-1.5%. This grid is the lookup that
-- get_llpa_adjustment() / get_total_rate() (scripts/pipeline_math.py)
-- consult: total_rate = par_base_rate + adjustment_pct.
--
-- Band convention matches the resolver query: a row covers
--   credit_score_min <= score <= credit_score_max
--   ltv_min < ltv <= ltv_max
-- ============================================================

CREATE TABLE IF NOT EXISTS llpa_adjustments (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agency           VARCHAR(20) NOT NULL,
    adjustment_type  VARCHAR(50) NOT NULL,
    credit_score_min INTEGER,
    credit_score_max INTEGER,
    ltv_min          NUMERIC,
    ltv_max          NUMERIC,
    property_type    VARCHAR(50),
    loan_purpose     VARCHAR(50),
    occupancy_type   VARCHAR(50),
    adjustment_pct   NUMERIC NOT NULL,
    effective_date   DATE DEFAULT CURRENT_DATE,
    description      TEXT,
    UNIQUE (agency, adjustment_type, credit_score_min, ltv_min,
            property_type, loan_purpose)
);

-- Fannie Mae LLPA grid (effective 2023+)
-- Source: Fannie Mae Loan-Level Price Adjustment Matrix.
-- Credit score x LTV adjustments (primary residence, SFR, purchase).
INSERT INTO llpa_adjustments
    (agency, adjustment_type, credit_score_min, credit_score_max,
     ltv_min, ltv_max, property_type, loan_purpose,
     adjustment_pct, description)
VALUES
-- >=780 credit
('fannie','credit_score_ltv', 780,999, 0,  60, 'sfr','purchase', -0.375,'>=780, <=60% LTV'),
('fannie','credit_score_ltv', 780,999, 60, 75, 'sfr','purchase',  0.000,'>=780, 60.01-75%'),
('fannie','credit_score_ltv', 780,999, 75, 80, 'sfr','purchase',  0.000,'>=780, 75.01-80%'),
('fannie','credit_score_ltv', 780,999, 80, 85, 'sfr','purchase',  0.000,'>=780, 80.01-85%'),
('fannie','credit_score_ltv', 780,999, 85, 90, 'sfr','purchase',  0.250,'>=780, 85.01-90%'),
('fannie','credit_score_ltv', 780,999, 90, 95, 'sfr','purchase',  0.250,'>=780, 90.01-95%'),
('fannie','credit_score_ltv', 780,999, 95, 97, 'sfr','purchase',  0.250,'>=780, 95.01-97%'),
-- 760-779 credit
('fannie','credit_score_ltv', 760,779, 0,  60, 'sfr','purchase', -0.375,'760-779, <=60%'),
('fannie','credit_score_ltv', 760,779, 60, 75, 'sfr','purchase',  0.000,'760-779, 60-75%'),
('fannie','credit_score_ltv', 760,779, 75, 80, 'sfr','purchase',  0.000,'760-779, 75-80%'),
('fannie','credit_score_ltv', 760,779, 80, 85, 'sfr','purchase',  0.250,'760-779, 80-85%'),
('fannie','credit_score_ltv', 760,779, 85, 90, 'sfr','purchase',  0.250,'760-779, 85-90%'),
('fannie','credit_score_ltv', 760,779, 90, 95, 'sfr','purchase',  0.500,'760-779, 90-95%'),
('fannie','credit_score_ltv', 760,779, 95, 97, 'sfr','purchase',  0.500,'760-779, 95-97%'),
-- 740-759 credit
('fannie','credit_score_ltv', 740,759, 0,  60, 'sfr','purchase',  0.000,'740-759, <=60%'),
('fannie','credit_score_ltv', 740,759, 60, 75, 'sfr','purchase',  0.250,'740-759, 60-75%'),
('fannie','credit_score_ltv', 740,759, 75, 80, 'sfr','purchase',  0.250,'740-759, 75-80%'),
('fannie','credit_score_ltv', 740,759, 80, 85, 'sfr','purchase',  0.250,'740-759, 80-85%'),
('fannie','credit_score_ltv', 740,759, 85, 90, 'sfr','purchase',  0.500,'740-759, 85-90%'),
('fannie','credit_score_ltv', 740,759, 90, 95, 'sfr','purchase',  0.750,'740-759, 90-95%'),
('fannie','credit_score_ltv', 740,759, 95, 97, 'sfr','purchase',  0.750,'740-759, 95-97%'),
-- 720-739 credit
('fannie','credit_score_ltv', 720,739, 0,  60, 'sfr','purchase',  0.000,'720-739, <=60%'),
('fannie','credit_score_ltv', 720,739, 60, 75, 'sfr','purchase',  0.250,'720-739, 60-75%'),
('fannie','credit_score_ltv', 720,739, 75, 80, 'sfr','purchase',  0.500,'720-739, 75-80%'),
('fannie','credit_score_ltv', 720,739, 80, 85, 'sfr','purchase',  0.500,'720-739, 80-85%'),
('fannie','credit_score_ltv', 720,739, 85, 90, 'sfr','purchase',  0.750,'720-739, 85-90%'),
('fannie','credit_score_ltv', 720,739, 90, 95, 'sfr','purchase',  1.000,'720-739, 90-95%'),
('fannie','credit_score_ltv', 720,739, 95, 97, 'sfr','purchase',  1.000,'720-739, 95-97%'),
-- 700-719 credit
('fannie','credit_score_ltv', 700,719, 0,  60, 'sfr','purchase',  0.000,'700-719, <=60%'),
('fannie','credit_score_ltv', 700,719, 60, 75, 'sfr','purchase',  0.500,'700-719, 60-75%'),
('fannie','credit_score_ltv', 700,719, 75, 80, 'sfr','purchase',  0.500,'700-719, 75-80%'),
('fannie','credit_score_ltv', 700,719, 80, 85, 'sfr','purchase',  0.750,'700-719, 80-85%'),
('fannie','credit_score_ltv', 700,719, 85, 90, 'sfr','purchase',  1.000,'700-719, 85-90%'),
('fannie','credit_score_ltv', 700,719, 90, 95, 'sfr','purchase',  1.250,'700-719, 90-95%'),
('fannie','credit_score_ltv', 700,719, 95, 97, 'sfr','purchase',  1.250,'700-719, 95-97%'),
-- 680-699 credit
('fannie','credit_score_ltv', 680,699, 0,  60, 'sfr','purchase',  0.000,'680-699, <=60%'),
('fannie','credit_score_ltv', 680,699, 60, 75, 'sfr','purchase',  0.500,'680-699, 60-75%'),
('fannie','credit_score_ltv', 680,699, 75, 80, 'sfr','purchase',  0.750,'680-699, 75-80%'),
('fannie','credit_score_ltv', 680,699, 80, 85, 'sfr','purchase',  1.000,'680-699, 80-85%'),
('fannie','credit_score_ltv', 680,699, 85, 90, 'sfr','purchase',  1.500,'680-699, 85-90%'),
('fannie','credit_score_ltv', 680,699, 90, 95, 'sfr','purchase',  1.500,'680-699, 90-95%'),
-- 660-679 credit
('fannie','credit_score_ltv', 660,679, 0,  60, 'sfr','purchase',  0.000,'660-679, <=60%'),
('fannie','credit_score_ltv', 660,679, 60, 75, 'sfr','purchase',  0.750,'660-679, 60-75%'),
('fannie','credit_score_ltv', 660,679, 75, 80, 'sfr','purchase',  1.000,'660-679, 75-80%'),
('fannie','credit_score_ltv', 660,679, 80, 85, 'sfr','purchase',  1.500,'660-679, 80-85%'),
('fannie','credit_score_ltv', 660,679, 85, 90, 'sfr','purchase',  2.000,'660-679, 85-90%'),
('fannie','credit_score_ltv', 660,679, 90, 95, 'sfr','purchase',  2.000,'660-679, 90-95%'),
-- 640-659 credit
('fannie','credit_score_ltv', 640,659, 0,  60, 'sfr','purchase',  0.500,'640-659, <=60%'),
('fannie','credit_score_ltv', 640,659, 60, 75, 'sfr','purchase',  1.250,'640-659, 60-75%'),
('fannie','credit_score_ltv', 640,659, 75, 80, 'sfr','purchase',  1.500,'640-659, 75-80%'),
('fannie','credit_score_ltv', 640,659, 80, 85, 'sfr','purchase',  2.000,'640-659, 80-85%'),
('fannie','credit_score_ltv', 640,659, 85, 90, 'sfr','purchase',  2.500,'640-659, 85-90%'),
-- 620-639 credit
('fannie','credit_score_ltv', 620,639, 0,  60, 'sfr','purchase',  0.500,'620-639, <=60%'),
('fannie','credit_score_ltv', 620,639, 60, 75, 'sfr','purchase',  1.500,'620-639, 60-75%'),
('fannie','credit_score_ltv', 620,639, 75, 80, 'sfr','purchase',  1.750,'620-639, 75-80%'),
('fannie','credit_score_ltv', 620,639, 80, 85, 'sfr','purchase',  2.250,'620-639, 80-85%'),
('fannie','credit_score_ltv', 620,639, 85, 90, 'sfr','purchase',  2.750,'620-639, 85-90%')

ON CONFLICT DO NOTHING;
