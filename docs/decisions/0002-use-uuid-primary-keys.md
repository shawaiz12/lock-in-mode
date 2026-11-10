# 0002: Use UUID for Primary Keys

## Context
Every database table requires a primary key to uniquely identify each row. Changing this strategy later requires migrating every table that references it, so the approach must be solidified before writing any tables. A core requirement of our application is that workouts must function and be logged offline.

## Options

### 1. Auto-increment Integer (1, 2, 3...)
* **Size:** Small (4–8 bytes)
* **Readability:** Easy to read
* **Security:** Guessable (e.g., `/users/5` hints that `/users/6` exists and reveals total user counts)
* **Generation:** Can only be created by the database (the server must know the next number)
* **Syncing:** High risk of ID collisions when merging data from multiple offline sources

### 2. UUID (3f9a1c2e-...)
* **Size:** Larger (16 bytes)
* **Readability:** Hard to read
* **Security:** Not guessable
* **Generation:** Any device can generate one without the database
* **Syncing:** Practically no collisions when merging data

## Decision
We will use **UUIDs** (implemented as `Guid` primary keys in EF Core) for all database tables.

The deciding factor is the offline support requirement. A phone without internet access that logs a workout must be able to assign an ID immediately. With integers, this is impossible because only the server knows the next available number. With UUIDs, the client device generates the ID locally and syncs it to the server later with no conflicts.

## Consequences
* **Positive:** Full support for offline data creation and seamless syncing.
* **Positive:** Prevents enumeration attacks (users cannot guess other record IDs or scrape total counts).
* **Negative:** Introduces a trade-off of slightly more storage space and marginally slower database indexes. At our anticipated scale (thousands of users, not billions), this performance penalty is irrelevant.