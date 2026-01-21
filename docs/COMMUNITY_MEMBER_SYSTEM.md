# Community Member VIP System - Implementation Guide

## 🎯 Overview

Add a Community Member system where VIP users automatically receive 15 minutes (900 seconds) of talk time every 30 days.

---

## 📋 Database Schema Changes

### Required Fields in `users` Table

Add these columns to your Supabase `users` table:

```sql
-- Run in Supabase SQL Editor
ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS is_community_member BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS last_community_refill TIMESTAMPTZ;

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_users_community ON public.users(is_community_member);
```

---

## 🔧 Backend Implementation (app.py)

### Step 1: Add Community Member Helper Function

Add this function after the `flush_pending_time()` function (around line 268):

```python
# ==========================================
# COMMUNITY MEMBER AUTO-REFILL LOGIC
# ==========================================

def check_and_refill_community_bonus(email: str) -> bool:
    """
    Checks if a Community Member is due for their monthly 15-minute refill.
    Returns True if refilled, False otherwise.
    """
    try:
        # Get user from Supabase
        response = supabase.table("users").select("*").eq("email", email).execute()
        
        if not response.data or len(response.data) == 0:
            return False
            
        user = response.data[0]
        
        # Check if user is a community member
        if not user.get("is_community_member"):
            return False

        last_refill_str = user.get("last_community_refill")
        should_refill = False
        now = datetime.now(timezone.utc)

        if not last_refill_str:
            # Never refilled -> Refill now
            should_refill = True
        else:
            try:
                # Parse timestamp
                last_refill = datetime.fromisoformat(last_refill_str.replace('Z', '+00:00'))
                if last_refill.tzinfo is None:
                    last_refill = last_refill.replace(tzinfo=timezone.utc)
                
                # Check if 30 days have passed
                if (now - last_refill).days >= 30:
                    should_refill = True
            except Exception as e:
                logger.error(f"Date parse error for community refill: {e}")
                should_refill = True  # Fail safe: give benefit

        if should_refill:
            try:
                # Add 15 minutes (900 seconds)
                current_talktime = int(user.get("talktime", 0))
                new_talktime = current_talktime + 900
                
                # Update in Supabase
                supabase.table("users").update({
                    "talktime": new_talktime,
                    "last_community_refill": now.isoformat()
                }).eq("email", email).execute()
                
                logger.info(f"💎 Community Bonus: Added 15 mins to {email}")
                return True
            except Exception as e:
                logger.error(f"Failed to apply community bonus: {e}")
                
        return False
        
    except Exception as e:
        logger.error(f"Error in check_and_refill_community_bonus: {e}")
        return False
```

### Step 2: Find and Update Existing Routes

**Find the route that returns user talktime** (search for a route that returns talktime data):

```python
# Add this check before returning talktime to user
# Example location - adapt to your actual route:

@app.route("/api/user/info")  # or whatever your route is called
def get_user_info():
    email = get_current_user_email()  # however you get the email
    
    # 1. Flush pending Redis time
    flush_pending_time(email)
    
    # 2. Check & Apply Monthly Community Refill (NEW!)
    refilled = check_and_refill_community_bonus(email)
    
    # 3. Get fresh user data
    response = supabase.table("users").select("*").eq("email", email).execute()
    user = response.data[0] if response.data else None
    
    return jsonify({
        "ok": True,
        "talktime": user.get("talktime", 0),
        "email": email,
        "is_community_member": user.get("is_community_member", False)  # NEW!
    })
```

### Step 3: Add Admin Routes

Add these routes near your other admin endpoints:

```python
# ==========================================
# ADMIN: COMMUNITY MEMBER MANAGEMENT
# ==========================================

@app.post("/api/admin/community/add")
@limiter.limit("50 per hour")
def add_community_member():
    """Promote a user to Community Member."""
    # Verify admin authentication (use your existing admin verification)
    # verify_admin_token() or however you verify admin
    
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    
    if not validate_email(email):
        raise AppError("Invalid email", status_code=400)
    
    try:
        # Check if user exists
        response = supabase.table("users").select("*").eq("email", email).execute()
        
        if not response.data or len(response.data) == 0:
            raise AppError("User not found. They must sign up first.", status_code=404)
        
        # Update user to community member
        supabase.table("users").update({
            "is_community_member": True
        }).eq("email", email).execute()
        
        logger.info(f"✅ Added community member: {email}")
        return jsonify({"ok": True, "message": f"{email} is now a Community Member!"})
        
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error adding community member: {e}")
        raise AppError("Database error", status_code=500)


@app.post("/api/admin/community/remove")
@limiter.limit("50 per hour")
def remove_community_member():
    """Remove community member status."""
    # Verify admin authentication
    
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    
    try:
        supabase.table("users").update({
            "is_community_member": False,
            "last_community_refill": None
        }).eq("email", email).execute()
        
        logger.info(f"✅ Removed community member: {email}")
        return jsonify({"ok": True, "message": f"{email} removed from Community."})
        
    except Exception as e:
        logger.error(f"Error removing community member: {e}")
        raise AppError("Database error", status_code=500)
```

### Step 4: Update Admin Users List

Find your `/api/admin/users` route and ensure it returns the `is_community_member` field:

```python
@app.get("/api/admin/users")
def get_all_users():
    # Your existing code...
    response = supabase.table("users").select("*").execute()
    
    users_list = []
    for user in response.data:
        users_list.append({
            "email": user.get("email"),
            "talktime": user.get("talktime", 0),
            "is_community_member": user.get("is_community_member", False),  # ADD THIS
            # ... other fields
        })
    
    return jsonify({"ok": True, "users": users_list})
```

---

## 🎨 Frontend Implementation

### Step 1: Update index.html

Find the profile section and add the badge container:

```html
<div class="profile-section">
    <div class="profile-container" style="position: relative;">
        <!-- NEW: Community Badge -->
        <div id="communityBadge" class="community-badge hidden">
            <i class="fas fa-crown"></i> VIP
        </div>
        
        <!-- Existing profile elements -->
        <div class="profile-ring"></div>
        <img id="profileImage" src="coach.jpg" alt="Ronit" class="profile-img">
    </div>
</div>
```

### Step 2: Update style.css

Add at the end of the file:

```css
/* ==========================================
   Community Member Badge
   ========================================== */
.community-badge {
    position: absolute;
    top: -10px;
    right: -10px;
    background: linear-gradient(135deg, #F59E0B 0%, #B45309 100%);
    color: white;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 6px 12px;
    border-radius: 20px;
    box-shadow: 0 4px 10px rgba(180, 83, 9, 0.4);
    z-index: 100;
    border: 2px solid white;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    gap: 5px;
    animation: popIn 0.5s ease-out;
}

@keyframes popIn {
    0% { transform: scale(0); opacity: 0; }
    100% { transform: scale(1); opacity: 1; }
}

.hidden { display: none !important; }
```

### Step 3: Update script.js

Find where you fetch user talktime and add community member check:

```javascript
// Inside your fetch talktime function
async function fetchUserTalktime() {
    try {
        const response = await fetch('/api/user/info', {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        const data = await response.json();
        
        if (data.ok) {
            const talktime = data.talktime || 0;
            sessionStorage.setItem('userTalktime', talktime.toString());
            
            // ✨ NEW: Check Community Status
            if (data.is_community_member) {
                const badge = document.getElementById('communityBadge');
                if (badge) {
                    badge.classList.remove('hidden');
                }
                console.log("👑 Community Member identified!");
            }
            
            updateTalktimeDisplay(talktime);
        }
    } catch (error) {
        console.error("Error fetching talktime:", error);
    }
}
```

---

## 📊 Admin Panel Updates

### Create admin-community.html or update admin.html

Add Community Management tab with this content:

```html
<div class="community-management">
    <h2><i class="fas fa-crown"></i> Community Members</h2>
    
    <div class="add-member-section">
        <h3>Add New Member</h3>
        <div style="display: flex; gap: 10px;">
            <input 
                type="email" 
                id="communityEmailInput" 
                placeholder="Enter user email..." 
                style="flex: 1; padding: 10px; border-radius: 8px;"
            >
            <button onclick="addCommunityMember()" class="btn btn-primary">
                Add Member
            </button>
        </div>
        <p style="font-size: 0.85rem; color: #666; margin-top: 8px;">
            * Members get 15 mins (900s) auto-refilled every 30 days.
        </p>
    </div>

    <table class="users-table">
        <thead>
            <tr>
                <th>Email</th>
                <th>Status</th>
                <th>Last Refill</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody id="communityMembersTable">
            <!-- Populated by JavaScript -->
        </tbody>
    </table>
</div>

<script>
async function addCommunityMember() {
    const email = document.getElementById('communityEmailInput').value.trim();
    if (!email) return alert("Please enter an email");
    
    try {
        const response = await fetch('/api/admin/community/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getAdminToken()}`
            },
            body: JSON.stringify({ email })
        });
        
        const data = await response.json();
        
        if (data.ok) {
            alert(data.message);
            document.getElementById('communityEmailInput').value = '';
            loadCommunityMembers(); // Refresh list
        } else {
            alert(data.message || "Failed to add member");
        }
    } catch (error) {
        alert("Error: " + error.message);
    }
}

async function removeCommunityMember(email) {
    if (!confirm(`Remove ${email} from Community?`)) return;
    
    try {
        await fetch('/api/admin/community/remove', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getAdminToken()}`
            },
            body: JSON.stringify({ email })
        });
        
        loadCommunityMembers();
    } catch (error) {
        alert("Error removing member");
    }
}
</script>
```

---

## ✅ Testing Checklist

1. **Database Schema**
   - [ ] Run SQL to add columns to users table
   - [ ] Verify columns exist in Supabase

2. **Backend**
   - [ ] Test `/api/admin/community/add`
   - [ ] Test `/api/admin/community/remove`
   - [ ] Test auto-refill logic (manually set `last_community_refill` to 31 days ago)

3. **Frontend**
   - [ ] Badge shows for community members
   - [ ] Badge hidden for regular users
   - [ ] Admin panel can add/remove members

---

## 🚀 Deployment Steps

1. Run SQL in Supabase to add columns
2. Update `app.py` with new functions and routes
3. Update frontend files (index.html, style.css, script.js)
4. Update admin panel
5. Restart server
6. Test with a test user

---

## 📝 Summary

**What Users Get:**
- 15 minutes (900 seconds) free every 30 days
- Automatic refill (lazy check when they view balance)
- VIP badge on their profile

**What Admins Get:**
- Easy interface to add/remove members
- See all community members at a glance
- Track refill dates

**Benefits:**
- No cron job needed (lazy evaluation)
- Simple database structure
- Reliable and performant
