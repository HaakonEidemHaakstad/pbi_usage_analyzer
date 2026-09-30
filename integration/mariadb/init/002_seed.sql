INSERT INTO dim_company (company_id, company_name, region, unused_legacy_text) VALUES
(1, 'Alpha Bolig', 'Øst', 'legacy-a'),
(2, 'Beta Eiendom', 'Vest', 'legacy-b'),
(3, 'Gamma Drift', 'Nord', 'legacy-c')
ON DUPLICATE KEY UPDATE company_name = VALUES(company_name);

INSERT INTO dim_account (account_id, account_name, account_group) VALUES
(3000, 'Salgsinntekt', 'Inntekt'),
(4000, 'Varekostnad', 'Kostnad'),
(5000, 'Lønn', 'Kostnad')
ON DUPLICATE KEY UPDATE account_name = VALUES(account_name);

INSERT INTO dim_department (department_id, department_name) VALUES
(10, 'Forvaltning'),
(20, 'Teknisk'),
(30, 'Administrasjon')
ON DUPLICATE KEY UPDATE department_name = VALUES(department_name);

INSERT INTO fact_ledger
(posting_date, company_id, account_id, department_id, amount, voucher_text, legacy_unused_column)
VALUES
('2025-01-10', 1, 3000, 10, 125000.00, 'Januar inntekt', 'unused-1'),
('2025-01-15', 1, 4000, 10, -25000.00, 'Innkjøp', 'unused-2'),
('2025-02-05', 2, 3000, 20, 98000.00, 'Februar inntekt', 'unused-3'),
('2025-02-20', 2, 5000, 20, -42000.00, 'Lønn', 'unused-4'),
('2025-03-11', 3, 3000, 30, 76000.00, 'Mars inntekt', 'unused-5');

INSERT INTO ledger_2024
(posting_date, company_id, account_id, department_id, amount, voucher_text)
VALUES
('2024-11-10', 1, 3000, 10, 112000.00, 'November inntekt'),
('2024-12-10', 2, 3000, 20, 91000.00, 'Desember inntekt');
