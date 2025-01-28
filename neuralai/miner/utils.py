import hashlib
import bittensor as bt
import urllib.parse
import aiohttp
import time
import os
import shutil
import base64
from dotenv import load_dotenv
from neuralai.miner.s3_bucket import s3_upload, generate_presigned_url

load_dotenv()

S3_BUCKET_USE = os.getenv("S3_BUCKET_USE")

def set_status(self, status: str="idle"):
    self.miner_status = status
    
def check_status(self):
    if self.miner_status == "idle":
        return True
    return False
    
def check_validator(self, uid: int, interval: int = 200):
    cur_time = time.time()
    bt.logging.debug(f"Checking validator for UID: {uid} : {self.validators[uid]}")
    
    if uid not in self.validators:
        bt.logging.debug("Adding new validator.")
        self.validators[uid] = {
            "start": cur_time,
            "requests": 1,
        }
    elif cur_time - self.validators[uid]["start"] > interval:
        bt.logging.debug("Resetting validator due to interval.")
        self.validators[uid] = {
            "start": cur_time,
            "requests": 1,
        }
    else:
        bt.logging.debug("Incrementing request count for existing validator.")
        self.validators[uid]["requests"] += 1
        return True
    
    return False

def read_file(file_path):
    try:
        mode = 'rb'
        with open(file_path, mode) as file:
            content = file.read()
        return content
    except FileNotFoundError:
        return f"File not found: {file_path}"
    except Exception as e:
        return str(e)


async def generate(self, synapse: bt.Synapse) -> bt.Synapse:
    url = urllib.parse.urljoin(self.config.generation.endpoint, "/generate_from_text/")
    timeout = synapse.timeout
    prompt = synapse.prompt_text
    
    extra_prompts = "Angled front view, solid color background, 3d model, high quality"
    enhanced_prompt = f"{prompt}, {extra_prompts}"
    
    if type(synapse).__name__ == "NATextSynapse":
        result = await _generate_from_text(gen_url=url, timeout=timeout, prompt=enhanced_prompt)

        if not result or not result.get('success'):
            bt.logging.warning("Result is None")
            return synapse

        abs_path = os.path.join('generate', result['path'])
        paths = {
            "prev": os.path.join(abs_path, 'img.jpg'),
            "glb": os.path.join(abs_path, 'mesh.glb'),
        }

        try:
            if S3_BUCKET_USE != "TRUE":
                print(paths["prev"])
                synapse.out_prev = base64.b64encode(read_file(paths["prev"])).decode('utf-8')
                synapse.out_glb = base64.b64encode(read_file(paths["glb"])).decode('utf-8')
                synapse.s3_addr = []
            else:
                bt.logging.info("Uploading to S3bucket")
                for key, path in paths.items():
                    file_name = os.path.basename(path)
                    s3_upload(path, f"{self.generation_requests}/{file_name}")
                    synapse.s3_addr.append(generate_presigned_url(f"{self.generation_requests}/{file_name}"))

            bt.logging.info("Valid result")

        except Exception as e:
            bt.logging.error(f"Error reading files: {e}")

    return synapse

async def _generate(self, synapse: bt.Synapse) -> bt.Synapse:
    timeout = synapse.timeout
    prompt = synapse.prompt_text
    start = time.time()
    
    if type(synapse).__name__ == "NATextSynapse":
        prompt = prompt.strip()
        hash_folder_name = hashlib.sha256(prompt.encode()).hexdigest()
        print(f"{prompt} : {hash_folder_name}\n")
        
        abs_path = os.path.join('/workspace/DB', hash_folder_name)
        if not os.path.exists(abs_path):
            # set_status(self, "generation")
            print("~~~~~~~~~~~~~~~~~Couldn't find the folder of image and 3D model. {abs_path}~~~~~~~~~~~~~~~~~\n\
                  ~~~~~~~~~~~~~~~~~~⛏Need to generate 3D model ⛏~~~~~~~~~~~~~~~~~")
            # extra_prompts = "Angled front view, solid color background, 3d model"
            extra_prompts = "Angled front view, solid color background, high quality, detailed textures, realistic lighting, emphasis on form and depth, suitable for 3D rendering."
            enhanced_prompt = f"{prompt}, {extra_prompts}"
            url = urllib.parse.urljoin(self.config.generation.endpoint, "/generate_from_text/")
            bt.logging.info(f"generation endpoint: {url}")
            result = await __generate_from_text(gen_url=url, timeout=170, prompt=prompt, output_dir = abs_path)
            set_status(self)
            if not result or not result.get('success'):
                bt.logging.warning("Not able to generate 3D models due to unkown issues")
                with open("../../bad_prompts.txt", "a") as file:
                    file.write(f"{prompt}\n")
                    
                return synapse

            abs_path = result['path']
            text_file_path = os.path.join(abs_path, 'prompt.txt')
            # Save the line in the text file
            with open(text_file_path, 'w') as text_file:
                text_file.write(prompt)
            try:                
                extra_db_path = '/workspace/DB_Extra'
                os.makedirs(extra_db_path, exist_ok=True)
                shutil.copytree(abs_path, os.path.join(extra_db_path, hash_folder_name))

            except:
                bt.logging.info("Error occured while copying ")
            paths = {
                "prev": os.path.join(abs_path, 'img.jpg'),
                "glb": os.path.join(abs_path, 'mesh.glb'),
            }

            try:
                synapse.out_prev = base64.b64encode(read_file(paths["prev"])).decode('utf-8')
                synapse.out_glb = base64.b64encode(read_file(paths["glb"])).decode('utf-8')
                synapse.s3_addr = []                
                bt.logging.info("Valid result")

            except Exception as e:
                bt.logging.error(f"Error reading files: {e}")

            return synapse
            
        paths = {
            "prev": os.path.join(abs_path, 'img.jpg'),
            "glb": os.path.join(abs_path, 'mesh.glb'),
        }

        try:         
            synapse.out_prev = base64.b64encode(read_file(paths["prev"])).decode('utf-8')
            synapse.out_glb = base64.b64encode(read_file(paths["glb"])).decode('utf-8')
            synapse.s3_addr = []            
            bt.logging.info("Valid result")

        except Exception as e:
            bt.logging.error(f"Error reading files: {e}")
        
        if time.time() - start <  2:
            time.sleep(1)
    return synapse

async def _generate_from_text(gen_url: str, timeout: int, prompt: str):
    async with aiohttp.ClientSession() as session:
        try:
            bt.logging.debug(f"=================================================")
            client_timeout = aiohttp.ClientTimeout(total=float(timeout))
            
            async with session.post(gen_url, timeout=client_timeout, data={"prompt": prompt}) as response:
                if response.status == 200:
                    result = await response.json()
                    print("Success:", result)
                else:
                    bt.logging.error(f"Generation failed. Please try again.: {response.status}")
                return result
        except aiohttp.ClientConnectorError:
            bt.logging.error(f"Failed to connect to the endpoint. Try to access again: {gen_url}.")
        except TimeoutError:
            bt.logging.error(f"The request to the endpoint timed out: {gen_url}")
        except aiohttp.ClientError as e:
            bt.logging.error(f"An unexpected client error occurred: {e} ({gen_url})")
        except Exception as e:
            bt.logging.error(f"An unexpected error occurred: {e} ({gen_url})")
    
    return None

async def __generate_from_text(gen_url: str, timeout: int, prompt: str, output_dir: str):
    async with aiohttp.ClientSession() as session:
        try:
            bt.logging.debug(f"=================================================")
            client_timeout = aiohttp.ClientTimeout(total=float(timeout))
            
            async with session.post(gen_url, timeout=client_timeout, json={"prompt": prompt, "output_dir": output_dir}) as response:
                if response.status == 200:
                    result = await response.json()
                    print("Success:", result)
                else:
                    bt.logging.error(f"Generation failed. Please try again.: {response.status}")
                return result
        except aiohttp.ClientConnectorError:
            bt.logging.error(f"Failed to connect to the endpoint. Try to access again: {gen_url}.")
        except TimeoutError:
            bt.logging.error(f"The request to the endpoint timed out: {gen_url}")
        except aiohttp.ClientError as e:
            bt.logging.error(f"An unexpected client error occurred: {e} ({gen_url})")
        except Exception as e:
            bt.logging.error(f"An unexpected error occurred: {e} ({gen_url})")
    
    return None

async def validate(validation_url: str, timeout: int, prompt: str, DATA_DIR: str):
    async with aiohttp.ClientSession() as session:
        try:
            bt.logging.debug(f"=================================================")
            client_timeout = aiohttp.ClientTimeout(total=float(timeout))
            
            async with session.post(validation_url, timeout=client_timeout, json={"prompt": prompt, "DATA_DIR": DATA_DIR}) as response:
                if response.status == 200:
                    result = await response.json()
                    print("Success:", result)
                else:
                    bt.logging.error(f"Validation failed. Please try again.: {response.status}")
                return result
        except aiohttp.ClientConnectorError:
            bt.logging.error(f"Failed to connect to the endpoint. Try to access again: {validation_url}.")
        except TimeoutError:
            bt.logging.error(f"The request to the endpoint timed out: {validation_url}")
        except aiohttp.ClientError as e:
            bt.logging.error(f"An unexpected client error occurred: {e} ({validation_url})")
        except Exception as e:
            bt.logging.error(f"An unexpected error occurred: {e} ({validation_url})")
    
    return None

async def get_score():
    validation_url = urllib.parse.urljoin("http://127.0.0.1:8094", "/validation/")
    validation_timeout = 4
    prompt = "ancient bronze shield with serpent motif and verdigris patina"
    DATA_DIR = "/workspace/DB_Extra/e0ac9d94dcd27294a2117948e7a2489c19de8ff240e92f95783eab763e90b6c2"
    result = await validate(validation_url=validation_url, timeout=validation_timeout, prompt=prompt, DATA_DIR = DATA_DIR)
    
    print(result["S0"] > 1)
    

import asyncio
def main():
    asyncio.run(get_score())
if __name__ == "__main__":
    start = time.time()
    main()
    print(f"{time.time()-start} seconds elapsed!!!")