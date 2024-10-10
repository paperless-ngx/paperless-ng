# Paperless NGX Development Environment

## Overview

Welcome to the Paperless NGX development environment! This setup uses VSCode DevContainers to provide a consistent and seamless development experience.

### What are DevContainers?

DevContainers are a feature in VSCode that allows you to develop within a Docker container. This ensures that your development environment is consistent across different machines and setups. By defining a containerized environment, you can eliminate the "works on my machine" problem.

### Advantages of DevContainers

- **Consistency**: Same environment for all developers.
- **Isolation**: Separate development environment from your local machine.
- **Reproducibility**: Easily recreate the environment on any machine.
- **Pre-configured Tools**: Include all necessary tools and dependencies in the container.

## DevContainer Setup

The DevContainer configuration provides up all the necessary services for Paperless NGX, including:

- Redis
- Gotenberg
- Tika

Data is stored using Docker volumes to ensure persistence across container restarts.

## Configuration Files

The setup includes debugging configurations (`launch.json`) and tasks (`tasks.json`) to help you manage and debug various parts of the project:

- **Backend Debugging:**
  - `manage.py runserver`
  - `manage.py document-consumer`
  - `celery`
- **Maintenance Tasks:**
  - Create superuser
  - Run migrations
  - Recreate virtual environment (`.venv` with `uv`)
  - Compile frontend assets

## Getting Started

### Step 1: Running the DevContainer

To start the DevContainer:

1. Open VSCode.
2. Open the project folder.
3. Open the command palette:
   - **Windows/Linux**: `Ctrl+Shift+P`
   - **Mac**: `Cmd+Shift+P`
4. Type and select `Dev Containers: Rebuild and Reopen in Container`.

VSCode will build and start the DevContainer environment.

### Step 2: Initial Setup

Once the DevContainer is up and running, perform the following steps:

1. **Compile Frontend Assets**:

   - Open the command palette:
     - **Windows/Linux**: `Ctrl+Shift+P`
     - **Mac**: `Cmd+Shift+P`
   - Select `Tasks: Run Task`.
   - Choose `Frontend Compile`.

2. **Run Database Migrations**:

   - Open the command palette:
     - **Windows/Linux**: `Ctrl+Shift+P`
     - **Mac**: `Cmd+Shift+P`
   - Select `Tasks: Run Task`.
   - Choose `Migrate Database`.

3. **Create Superuser**:
   - Open the command palette:
     - **Windows/Linux**: `Ctrl+Shift+P`
     - **Mac**: `Cmd+Shift+P`
   - Select `Tasks: Run Task`.
   - Choose `Create Superuser`.

### Debugging and Running Services

You can start and debug backend services either as debugging sessions via `launch.json` or as tasks.

#### Using `launch.json`:

1. Press `F5` or go to the **Run and Debug** view in VSCode.
2. Select the desired configuration:
   - `Runserver`
   - `Document Consumer`
   - `Celery`

#### Using Tasks:

1. Open the command palette:
   - **Windows/Linux**: `Ctrl+Shift+P`
   - **Mac**: `Cmd+Shift+P`
2. Select `Tasks: Run Task`.
3. Choose the desired task:
   - `Runserver`
   - `Document Consumer`
   - `Celery`

### Additional Maintenance Tasks

Additional tasks are available for common maintenance operations:

- **Recreate .venv**: For setting up the virtual environment using `uv`.
- **Migrate Database**: To apply database migrations.
- **Create Superuser**: To create an admin user for the application.

## Let's Get Started!

Follow the steps above to get your development environment up and running. Happy coding!
