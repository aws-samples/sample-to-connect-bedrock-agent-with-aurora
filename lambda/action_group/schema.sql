-- Create schemas
CREATE SCHEMA academics;
CREATE SCHEMA staff;
CREATE SCHEMA facilities;
CREATE SCHEMA research;
-- Academics Schema
CREATE TABLE academics.departments (
    department_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(10) UNIQUE NOT NULL
);
CREATE TABLE academics.courses (
    course_id SERIAL PRIMARY KEY,
    department_id INTEGER REFERENCES academics.departments(department_id),
    code VARCHAR(20) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    credits INTEGER NOT NULL
);
CREATE TABLE academics.students (
    student_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    date_of_birth DATE NOT NULL,
    enrollment_date DATE NOT NULL,
    major_department_id INTEGER REFERENCES academics.departments(department_id)
);
CREATE TABLE academics.enrollments (
    enrollment_id SERIAL PRIMARY KEY,
    student_id INTEGER REFERENCES academics.students(student_id),
    course_id INTEGER REFERENCES academics.courses(course_id),
    semester VARCHAR(20) NOT NULL,
    year INTEGER NOT NULL,
    grade CHAR(2)
);
-- Staff Schema
CREATE TABLE staff.employees (
    employee_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hire_date DATE NOT NULL,
    position VARCHAR(100) NOT NULL
);
CREATE TABLE staff.salaries (
    salary_id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES staff.employees(employee_id),
    amount DECIMAL(10, 2) NOT NULL,
    effective_date DATE NOT NULL
);
-- Facilities Schema
CREATE TABLE facilities.buildings (
    building_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    address VARCHAR(200) NOT NULL,
    construction_year INTEGER
);
CREATE TABLE facilities.rooms (
    room_id SERIAL PRIMARY KEY,
    building_id INTEGER REFERENCES facilities.buildings(building_id),
    room_number VARCHAR(20) NOT NULL,
    capacity INTEGER,
    room_type VARCHAR(50) NOT NULL
);
CREATE TABLE facilities.equipment (
    equipment_id SERIAL PRIMARY KEY,
    room_id INTEGER REFERENCES facilities.rooms(room_id),
    name VARCHAR(100) NOT NULL,
    purchase_date DATE,
    last_maintenance_date DATE
);
-- Research Schema
CREATE TABLE research.projects (
    project_id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,
    funding_amount DECIMAL(12, 2)
);
CREATE TABLE research.publications (
    publication_id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    authors TEXT NOT NULL,
    publication_date DATE,
    journal VARCHAR(200),
    doi VARCHAR(100)
);
CREATE TABLE research.project_members (
    project_id INTEGER REFERENCES research.projects(project_id),
    employee_id INTEGER REFERENCES staff.employees(employee_id),
    role VARCHAR(50) NOT NULL,
    PRIMARY KEY (project_id, employee_id)
);
-- Create indexes for performance
CREATE INDEX idx_courses_department ON academics.courses(department_id);
CREATE INDEX idx_enrollments_student ON academics.enrollments(student_id);
CREATE INDEX idx_enrollments_course ON academics.enrollments(course_id);
CREATE INDEX idx_salaries_employee ON staff.salaries(employee_id);
CREATE INDEX idx_rooms_building ON facilities.rooms(building_id);
CREATE INDEX idx_equipment_room ON facilities.equipment(room_id);
CREATE INDEX idx_project_members_project ON research.project_members(project_id);
CREATE INDEX idx_project_members_employee ON research.project_members(employee_id);
-- Add some sample data
INSERT INTO academics.departments (name, code) VALUES 
('Computer Science', 'CS'),
('Physics', 'PHY'),
('Biology', 'BIO');
INSERT INTO academics.courses (department_id, code, title, credits) VALUES
(1, 'CS101', 'Introduction to Programming', 3),
(2, 'PHY201', 'Classical Mechanics', 4),
(3, 'BIO301', 'Genetics', 4);
INSERT INTO academics.students (first_name, last_name, date_of_birth, enrollment_date, major_department_id) VALUES
('Alice', 'Johnson', '2000-05-15', '2022-09-01', 1),
('Bob', 'Smith', '2001-03-22', '2022-09-01', 2);
INSERT INTO staff.employees (first_name, last_name, email, hire_date, position) VALUES
('John', 'Doe', 'john.doe@university.edu', '2015-08-01', 'Professor'),
('Jane', 'Doe', 'jane.doe@university.edu', '2018-01-15', 'Associate Professor');
INSERT INTO facilities.buildings (name, address, construction_year) VALUES
('Science Building', '123 University Ave', 1985),
('Library', '456 Campus Road', 1990);
INSERT INTO research.projects (title, description, start_date, end_date, funding_amount) VALUES
('AI in Education', 'Exploring AI applications in higher education', '2023-01-01', '2025-12-31', 500000.00),
('Quantum Computing Advances', 'Research on quantum algorithms', '2022-07-01', '2024-06-30', 750000.00);

INSERT INTO research.publications (title, authors, publication_date, journal, doi) VALUES
('AI in Higher Education: Challenges and Opportunities', 'John Doe, Jane Smith', '2023-03-15', 'Journal of Higher Education', '10.1000/12345'),
('Quantum Algorithms: A Survey', 'Alice Johnson, Bob Smith', '2022-09-01', 'Journal of Quantum Computing', '10.1000/67890');

INSERT INTO research.project_members (project_id, employee_id, role) VALUES
(1, 1, 'Principal Investigator'),
(1, 2, 'Co-Investigator'),
(2, 2, 'Principal Investigator');