# MO's To Be Close — Process Flow

## Information

The system is manual and is to be changed to automation.

## Requirements

- Upload PDF
- Verification that the record exists in the system
- If marked Done in our system, we must check in Odoo that the state is Done
- Login auth into the system uses Odoo access (use Odoo account for login)

## Step 1

1. New Record — named by SO.
2. Uploading PDF
   - Upload the PDF
   - Fetch the list data in the PDF and add it
     - Separate the **Information** and the **List data**
       - Information is added to the Step 1 record to complete its info — see [step1/1.png](step1/1.png)
         (Sold To, Tel. No., Fax No., ATTN, Date, Invoice No., Container No., Seal No., Destination)
       - Get all list data from the PDF and save it into the system — see [step1/2.png](step1/2.png)
         (External Code, Description, UM, Number of Packages, Net Weight, Gross Weight, CBM, Qty)
   - This is how it looks when recorded in the system — see [step1/3.png](step1/3.png)
     (Invoice No, External Code, Description, Qty)
3. Save
4. A list where we can check the dataset records.

## Step 2

### Requirement

- Get all states: **Confirmed**, **In Progress**, **To Close**

### Process

1. In Odoo Manufacturing Orders
   - Search the SO# coming from the Invoice No., e.g. `S04743` — search on Odoo by **Source**. See [step2/1.png](step2/1.png)
   - Find the match of the External Code from the PDF list against the Reference list from Odoo (the result after the search). The state must be one of the states in the requirement above. See [step2/2.png](step2/2.png)
   - For each match found, also check the **Transfers**. See [step2/3.png](step2/3.png)
   - It has another relation — that part is also recorded. Save the related data **except status Done**. See [step2/4.png](step2/4.png)
     - Saving data required only:
       - Reference as SPF and Status
2. Generate view result after.
   - Fields required:

     | Field | Source |
     |---|---|
     | SO# | Invoice No. |
     | FG Code | External Code |
     | FG | Description |
     | Qty | Qty |
     | MO | Reference |
     | State | State |

   - Relation on reference (MO): SPF and Status

## Step 3

1. Progress monitoring module
   - The first generate shows the in-progress status, which means not done. Add a module where we can see the progress of what is not done until it is done, for each row.
   - Include every detailed relation, which is also monitored for status.
   - Can be exported in **PDF** or **Excel** format.
   - Generate report, exportable to PDF or Excel. The report is based on the recorded SO. The data comes from the point where we generate from Odoo and save it here in the system.
2. User mark as done
   - Users can update / mark check if it is done from their side, and it is dated.
   - Each data row can be mark-checked as done.
3. System counter check
   - When users mark Done, the system does a counter check in Odoo whether the state/status is Done. An additional field determines that it is **confirmed done**.
   - Only **Checker / Supervisor** users are allowed to update the final confirmation in the system. If this happens (confirmation not confirmed by the system), a comment is required.
   - Logs are included for everything that happens, in specific sections.

## Step 4

_Pending — to be provided._
