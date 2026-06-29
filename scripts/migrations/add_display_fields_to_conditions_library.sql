-- Add review_area to conditions_library (workbench data-driven layer).
-- Maps each condition category to the review-area label shown in the UI strip.

ALTER TABLE conditions_library
ADD COLUMN IF NOT EXISTS review_area VARCHAR(50)
DEFAULT NULL;

-- Maps category -> review area shown in the UI strip
UPDATE conditions_library SET review_area = 'Identity'     WHERE category = 'fraud';
UPDATE conditions_library SET review_area = 'Income'       WHERE category = 'income';
UPDATE conditions_library SET review_area = 'Assets'       WHERE category = 'asset';
UPDATE conditions_library SET review_area = 'Underwriting' WHERE category IN ('credit', 'product');
UPDATE conditions_library SET review_area = 'Employment'   WHERE category = 'employment';
UPDATE conditions_library SET review_area = 'Compliance'   WHERE category = 'compliance';
UPDATE conditions_library SET review_area = 'Property'     WHERE category = 'property';
UPDATE conditions_library SET review_area = 'Closing'      WHERE category = 'closing';
UPDATE conditions_library SET review_area = 'Title'        WHERE category = 'title';
