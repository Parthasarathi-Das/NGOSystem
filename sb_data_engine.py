from supabase import create_client
from account import *
import requests
from dotenv import load_dotenv
import os
import mimetypes

SUPABASE_URL = "https://hfuonfvrrzitmqegykod.supabase.co"
load_dotenv("dbpw.env")
SUPABASE_KEY  = os.getenv("secret_key")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


class OTP_Auth:
    def send_otp_to_email(email:str):
        try:
            res = supabase.auth.sign_in_with_otp({
                "email": email
            })
            print(f"OTP sent to email {email}")
            return True
        except Exception as e:
            print(str(e))
            return False
    
    def verify_email_otp(email: str, otp):
        try:
            res = supabase.auth.verify_otp({
                "email": email,
                "token": otp,
                "type": "email"
            })
            return res.session is not None
        except Exception as e:
            print(str(e))
            return False









class Donor_DB:
    table = "Donor_Profile"
    photo_bucket = "donor_photos"
    def insert_profile(profile: Donor_Profile):
        data = {
            "email" : profile.email,
            "phone_no" : profile.phone_no,
            "full_name": profile.name,
            "address": profile.addr,
            "district": profile.district,
            "pin_code": profile.pin,
            "prof": profile.prof,
            "password" : profile.pw
        }
        try:
            response = supabase.table(Donor_DB.table).insert(data).execute()
            print(response)
            return True
        except:
            return False
    
    def update_profile(id:int, profile: Donor_Profile):
        data = {
            "phone_no" : profile.phone_no,
            "full_name": profile.name,
            "address": profile.addr,
            "district": profile.district,
            "pin_code": profile.pin,
            "prof": profile.prof,
        }
        try:
            response = supabase.table(Donor_DB.table) \
            .update(data) \
            .eq("id", id) \
            .execute()
            print(response)
            return True
        except:
            return False
        
    def get_id_through_email_password(email, pw):
        try:
            response = supabase.table("Donor_Profile") \
            .select("id") \
            .eq("email", email) \
            .eq("password", pw) \
            .execute()
            data = response.data
            if data:
                print(data[0]["id"])
                return True, data[0]["id"]
            else:
                return False, None
        except:
            return False, None

    def read_profile(id:int):
        try:
            response = supabase.table(Donor_DB.table) \
                .select("*") \
                .eq("id", id)\
                .execute()
            data = response.data
            if data:
                print(data[0]["id"])
                return True, data[0]
            else:
                return False, None

        except:
            return False, None
    

    def read_top_10_profiles():
        try:
            response = supabase.table(Donor_DB.table) \
            .select("*") \
            .order("score", desc=True) \
            .limit(10) \
            .execute()
            data = response.data
            if data:
                print(data)
                return True, data[0]
            else:
                return False, None

        except:
            return False, None

    def update_password(email, pw):
        try:
            response = supabase.table(Donor_DB.table) \
            .update({"password": pw}) \
            .eq("email", email) \
            .execute()
            print(response)
            return True
        except:
            return False
        
    def verify_email(email):
        try:
            response = supabase.table(Donor_DB.table) \
            .select("id") \
            .eq("email", email) \
            .execute()
            data = response.data
            if data:
                print(data[0]["id"])
                return True
            else:
                return False
        except:
            return False

    def get_password(id):
        try:
            response = supabase.table("Donor_Profile") \
            .select("password") \
            .eq("id", id) \
            .execute()
            data = response.data
            if data:
                print(data[0]["id"])
                return True, data[0]["id"]
            else:
                return False, None
        except:
            return False, None
        
    def delete_profile_with_email(user_id, email):
        try:
            response = supabase.table(Donor_DB.table) \
                .delete() \
                .eq("id", user_id) \
                .eq("email", email) \
                .execute()

            if response.data:
                return True
            else:
                return False

        except Exception as e:
            print(e)
            return False
        


class Crisis_DB:
    table = "Crisis_Report"

    def insert_record(crisis: Crisis_Account):
        data = {
            "name" : crisis.name,
            "phone_no" : crisis.phone_no,
            "address": crisis.addr,
            "district": crisis.district,
            "pin_code": crisis.pin,
            "description":  crisis.desc
        }
        try:
            response = supabase.table(Crisis_DB.table).insert(data).execute()
            print(response)
            return True
        except:
            return False


# success, message =Donor_DB.download_photo(2, "static") #Donor_DB.upload_or_update_photo(2,"static\profile_pics\\abc312967_gmail_com.jpeg")
# print(success)
# print(message)
    '''def upload_or_update_photo(id, file_path):
        try:
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = "image/jpeg"

            ext = os.path.splitext(file_path)[1] 
            storage_path = f"{id}/profile" + ext

            with open(file_path, "rb") as f:
                supabase.storage.from_(Donor_DB.photo_bucket).upload(
                    storage_path,
                    f,
                    {
                        "content-type": mime_type,
                        "upsert": "true"
                    }
                )
            f.close()

            public_url = supabase.storage.from_(Donor_DB.photo_bucket) \
            .get_public_url(storage_path)

            response = supabase.table(Donor_DB.table) \
                .update({"pic_url": public_url}) \
                .eq("id", id) \
                .execute()

            if response.data:
                return True, "Uploaded SuccessFully"
            else:
                return False, "No row updated"

        except Exception as e:
            return False, str(e)
        
    def download_photo(id, save_dir):
        try:
            response = supabase.table(Donor_DB.table) \
                .select("pic_url") \
                .eq("id", id) \
                .limit(1) \
                .execute()

            if not response.data:
                return False, "User not found or no photo"

            photo_url = response.data[0]["pic_url"]

            if not photo_url:
                return False, "No photo URL stored"

            img_response = requests.get(photo_url, timeout=10, stream=True)
            if img_response.status_code != 200:
                return False, f"Failed to download. Status code: {img_response.status_code}"

            content_type = img_response.headers.get('Content-Type', '')
            if 'text/html' in content_type or 'application/json' in content_type:
                return False, "Downloaded content is not an image (Access Denied or Not Found)"

            if 'image/png' in content_type:
                ext = ".png"
            elif 'image/webp' in content_type:
                ext = ".webp"
            else:
                ext = os.path.splitext(photo_url)[1] or ".jpg"

            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"donor{id}{ext}")

            with open(save_path, "wb") as f:
                for chunk in img_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True, save_path

        except Exception as e:
            return False, str(e)
    
    def remove_photo(id):
        try:
            response = supabase.table(Donor_DB.table) \
                .select("pic_url") \
                .eq("id", id) \
                .limit(1) \
                .execute()

            if not response.data:
                return False, "User not found"

            photo_url = response.data[0]["pic_url"]

            if not photo_url:
                return False, "No photo to delete"

            ext = os.path.splitext(photo_url)[1]
            storage_path = storage_path = f"{id}/profile{ext}"
            supabase.storage.from_(Donor_DB.photo_bucket).remove([storage_path])

            update_res = supabase.table(Donor_DB.table) \
                .update({"pic_url": None}) \
                .eq("id", id) \
                .execute()

            if update_res.data:
                return True, "PIC removed"
            else:
                return False, "DB update failed"

        except Exception as e:
            return False, str(e)'''