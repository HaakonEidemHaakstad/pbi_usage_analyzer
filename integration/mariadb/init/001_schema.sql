CREATE TABLE IF NOT EXISTS dim_company (
    company_id INT PRIMARY KEY,
    company_name VARCHAR(120) NOT NULL,
    region VARCHAR(60),
    unused_legacy_text VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS dim_account (
    account_id INT PRIMARY KEY,
    account_name VARCHAR(120) NOT NULL,
    account_group VARCHAR(60)
);

CREATE TABLE IF NOT EXISTS dim_department (
    department_id INT PRIMARY KEY,
    department_name VARCHAR(120) NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_ledger (
    ledger_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    posting_date DATE NOT NULL,
    company_id INT NOT NULL,
    account_id INT NOT NULL,
    department_id INT,
    amount DECIMAL(18,2) NOT NULL,
    voucher_text VARCHAR(255),
    legacy_unused_column VARCHAR(255),
    CONSTRAINT fk_fact_company FOREIGN KEY (company_id) REFERENCES dim_company(company_id),
    CONSTRAINT fk_fact_account FOREIGN KEY (account_id) REFERENCES dim_account(account_id),
    CONSTRAINT fk_fact_department FOREIGN KEY (department_id) REFERENCES dim_department(department_id)
);

CREATE TABLE IF NOT EXISTS ledger_2024 (
    ledger_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    posting_date DATE NOT NULL,
    company_id INT NOT NULL,
    account_id INT NOT NULL,
    department_id INT,
    amount DECIMAL(18,2) NOT NULL,
    voucher_text VARCHAR(255)
);

CREATE OR REPLACE VIEW vw_fact_ledger_narrow AS
SELECT
    posting_date,
    company_id,
    account_id,
    department_id,
    amount
FROM fact_ledger;
