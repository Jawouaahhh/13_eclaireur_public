import json
import sys
from pathlib import Path
import requests
import pandas as pd
import logging

communities_path = str(Path(__file__).resolve().parents[1] /'communities')
if communities_path not in sys.path:
    sys.path.insert(0, communities_path)

from communities_selector import CommunitiesSelector

utils_path = str(Path(__file__).resolve().parents[2] / 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

from files_operation import load_from_url

# Configure the logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class DataGouvSearcher():
    def __init__(self,config):
        self.scope = CommunitiesSelector(config["communities"])
        self.datagouv_ids = self.scope.get_datagouv_ids() # dataframe with siren and id-datagouv columns
        self.datagouv_ids_list = self.datagouv_ids["id-datagouv"].to_list()

        self.dataset_catalog_df = load_from_url(config["datagouv"]["datasets"]["url"], columns_to_keep=config["datagouv"]["datasets"]["columns"])
        
        self.dataset_catalog_df = self.filter_by(self.dataset_catalog_df, "organization_id", self.datagouv_ids_list)
        # join siren to dataset_catalog_df based on organization_id
        self.dataset_catalog_df = self.dataset_catalog_df.merge(self.datagouv_ids, left_on="organization_id", right_on="id-datagouv", how="left")
        self.dataset_catalog_df.drop(columns=['id-datagouv'], inplace=True)

        self.datafile_catalog_df = load_from_url(config["datagouv"]["datafiles"]["url"])
        self.datafile_catalog_df.columns=list(map(lambda x: x.replace("dataset.organization_id","organization_id"), self.datafile_catalog_df.columns.to_list()))
        self.datafile_catalog_df = self.filter_by(self.datafile_catalog_df, "organization_id", self.datagouv_ids_list)
        # join siren to datafile_catalog_df based on organization_id
        self.datafile_catalog_df = self.datafile_catalog_df.merge(self.datagouv_ids, left_on="organization_id", right_on="id-datagouv", how="left")
        self.datafile_catalog_df.drop(columns=['id-datagouv'], inplace=True)
        
    def filter_by(self, df, column, value, return_mask=False):

        if isinstance(value, str):
            mask = df[column].str.contains(value, case=False, na=False)
        else:
            mask = df[column].isin(value)
        return mask if return_mask else df[mask]
    
    def get_datafiles_by_title_and_desc(self,title_filter,description_filter):
        # First we get the masks on the data:
        mask_desc = self.filter_by(self.dataset_catalog_df, "description", description_filter, return_mask=True)
        logger.info(f"Nombre de datasets correspondant au filtre de description : {mask_desc.sum()}")

        mask_titles = self.filter_by(self.dataset_catalog_df, "title", title_filter, return_mask=True)
        logger.info(f"Nombre de datasets correspondant au filtre de titre : {mask_titles.sum()}")

        filtered_catalog_df = self.dataset_catalog_df[(mask_titles | mask_desc)]

        # Now we merge with files 
        filtered_files = filtered_catalog_df[["siren","id","title","description","organization","frequency"]].merge(self.datafile_catalog_df[["dataset.id","format","created_at","url"]],left_on="id",right_on="dataset.id",how="left")
        filtered_files.drop(columns=['dataset.id'], inplace=True)
        # Food for thought, do we need id from datafile ?
        # print(filtered_files.columns)
        # print(filtered_files.iloc[0])
        return filtered_files
    
    def check_columns(self,dataframe, columns):
        lowercase_columns = [col.lower() for col in dataframe.columns]
        lowercase_check = [col.lower() in lowercase_columns for col in columns]
        return all(lowercase_check)

    def get_preferred_format(self,records):
        preferred_formats = ["csv", "xls", "json", "zip"] # Could be put outside

        for format in preferred_formats:
            for record in records:
                if record.get("format: ") == format:
                    return record

        for record in records:
            if record.get("format: ") is not None:
                return record

        return records[0] if records else None


    def get_files_by_org_from_api(self,url,organization_id,title_filter,description_filter, column_filter):
        params = {"organization": organization_id}
        scoped_files = []
        while True:
            response = requests.get(url, params=params)
            try:
                response.raise_for_status()
            except:
                break
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Error while decoding json from {url} : {e}")
                break
            for result in data["data"]:
                files = []
                if any(word in result["title"].lower() for word in title_filter):
                    keyword_in_title = True
                else:
                    keyword_in_title = False

                if any(word in result["description"].lower() for word in description_filter):
                    keyword_in_description = True
                else:
                    keyword_in_description = False
                montant_col = None
                for resource in result["resources"]:
                    if resource["description"] is None:
                        montant_col = None
                    elif any(word in resource["description"].lower() for word in column_filter):
                        montant_col = True
                    else:
                        montant_col = False

                    files.append({"organization-id":result["organization"]["id"], "organization":result["organization"]["name"],"title":result["title"],"description":result["description"],"id":result["id"],"frequency":result["frequency"],"format":resource["format"],"url":resource["url"],"created_at":resource["created_at"],'montant_col':montant_col,"keyword_in_description":keyword_in_description,"keyword_in_title":keyword_in_title})
                if (keyword_in_description or keyword_in_title or montant_col) and len(files)>0:
                    scoped_files.append(self.get_preferred_format(files))
            if data["next_page"]:
                url=data["next_page"]
                params = {}
            else:
                break
        return scoped_files

    def get_datafiles_by_content(self,url,title_filter,description_filter,column_filter):
        all_files = []

        for orga in self.datagouv_ids_list:
            cur_files = self.get_files_by_org_from_api(url,orga,title_filter,description_filter,column_filter)
            all_files = all_files + cur_files

        bottom_up_files_df = pd.DataFrame(all_files)
        # Join with siren based on organization
        bottom_up_files_df = bottom_up_files_df.merge(self.datagouv_ids, left_on="organization-id", right_on="id-datagouv", how="left")
        bottom_up_files_df.drop(columns=['id-datagouv'], inplace=True)
        bottom_up_files_df.drop(columns=['organization-id'], inplace=True)
        return bottom_up_files_df[(bottom_up_files_df.keyword_in_title|bottom_up_files_df.keyword_in_description)&bottom_up_files_df.montant_col]
    
    def log_basic_info(self,df):
        logger.info(f"Nombre de datasets correspondant au filtre de titre ou de description : {df.id.nunique()}")
        logger.info(f"Nombre de fichiers : {df.shape[0]}")
        logger.info(f"Nombre de fichiers uniques : {df.url.nunique()}")
        logger.info(f"Nombre de fichiers par format : {df.groupby('format').size().to_dict()}")
        logger.info(f"Nombre de fichiers par fréquence : {df.groupby('frequency').size().to_dict()}")
    
    def get_datafiles(self, search_config, method="all"):
        if not method=="bu_only":
            topdown_datafiles = self.get_datafiles_by_title_and_desc(search_config["title_filter"],search_config["description_filter"])
            logger.info("Topdown datafiles basic info :")
            self.log_basic_info(topdown_datafiles)

        if not method=="td_only":
            bottomup_datafiles = self.get_datafiles_by_content(search_config["api"]["url"],search_config["api"]["title"],search_config["api"]["description"],search_config["api"]["columns"])
            logger.info("Bottomup datafiles basic info :")
            self.log_basic_info(bottomup_datafiles)
            
        match method:
            case "td_only":
                datafiles = topdown_datafiles
            case "bu_only":
                datafiles = bottomup_datafiles
            case "all":
                # Merge topdown and bottomup: bottomup has 3 additional columns that must be dropped
                datafiles = pd.concat([topdown_datafiles, bottomup_datafiles], ignore_index=False)
                datafiles.drop_duplicates(subset=["url"], inplace=True)     # Drop duplicates based on url
                logger.info("Total datafiles basic info :")
                self.log_basic_info(datafiles)
            case _:
                raise ValueError(f"Unknown Datafiles Searcher method {method} : should be one of ['td_only', 'bu_only', 'all']")

        return datafiles